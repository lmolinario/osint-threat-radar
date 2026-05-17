import os
import time
import threading
from typing import Any, Dict, Optional, Tuple, List

import httpx

from app.collectors.static_provider_cache import fetch_cached_aircraft_italy

# (min_lat, max_lat, min_lon, max_lon)
IT_BBOX: Tuple[float, float, float, float] = (35.0, 48.0, 6.0, 19.0)

OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)

# Render-friendly defaults: avoid frequent provider calls and unbounded memory growth.
TTL_OK = int(os.getenv("OPENSKY_CACHE_TTL_OK", "60"))
TTL_ERROR = int(os.getenv("OPENSKY_CACHE_TTL_ERROR", "180"))
OPENSKY_TIMEOUT = float(os.getenv("OPENSKY_TIMEOUT", "8"))
OPENSKY_MAX_CACHE_KEYS = int(os.getenv("OPENSKY_MAX_CACHE_KEYS", "24"))
TOKEN_REFRESH_MARGIN = 30

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()

_TOKEN_CACHE: Dict[str, Any] = {
    "access_token": None,
    "expires_at": 0.0,
}
_TOKEN_LOCK = threading.Lock()


def _normalize_bbox(bbox: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """
    Normalize viewport coordinates before using them as cache keys.

    Leaflet sends slightly different decimal coordinates after every pan/zoom.
    Without normalization, each map movement creates a new cache entry and can
    keep increasing memory usage on small Render instances.
    """
    min_lat, max_lat, min_lon, max_lon = bbox

    # Clamp to valid geographic bounds.
    min_lat = max(-90.0, min(90.0, min_lat))
    max_lat = max(-90.0, min(90.0, max_lat))
    min_lon = max(-180.0, min(180.0, min_lon))
    max_lon = max(-180.0, min(180.0, max_lon))

    # Keep cache buckets coarse enough for reuse but precise enough for the map.
    return (
        round(min_lat, 1),
        round(max_lat, 1),
        round(min_lon, 1),
        round(max_lon, 1),
    )


def _bbox_key(b: Tuple[float, float, float, float]) -> str:
    return f"{b[0]:.1f},{b[1]:.1f},{b[2]:.1f},{b[3]:.1f}"


def _now() -> float:
    return time.time()


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _empty(error: str, stale: bool = False) -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "generated_at": _iso_now(),
        "opensky_time": None,
        "count": 0,
        "error": error,
        "stale": stale,
        "rate_limit_remaining": None,
        "retry_after_seconds": None,
        "features": [],
    }


def _get_cache(key: str) -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        return _CACHE.get(key)


def _prune_cache_locked() -> None:
    """Keep only the most recent cache buckets to avoid memory growth."""
    if len(_CACHE) <= OPENSKY_MAX_CACHE_KEYS:
        return

    ordered_keys = sorted(_CACHE, key=lambda k: float(_CACHE[k].get("ts", 0.0)))
    keys_to_remove = ordered_keys[: max(0, len(_CACHE) - OPENSKY_MAX_CACHE_KEYS)]
    for key in keys_to_remove:
        _CACHE.pop(key, None)


def _set_cache(key: str, data: Dict[str, Any], ttl: int) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = {
            "ts": _now(),
            "ttl": ttl,
            "data": data,
        }
        _prune_cache_locked()


def _is_cache_valid(hit: Dict[str, Any]) -> bool:
    return (_now() - hit["ts"]) < hit["ttl"]


def _is_default_italy_bbox(bbox: Tuple[float, float, float, float]) -> bool:
    return all(abs(a - b) < 0.0001 for a, b in zip(bbox, IT_BBOX))


def _get_oauth_token() -> Optional[str]:
    client_id = os.getenv("OPENSKY_CLIENT_ID")
    client_secret = os.getenv("OPENSKY_CLIENT_SECRET")

    if not client_id or not client_secret:
        return None

    with _TOKEN_LOCK:
        cached_token = _TOKEN_CACHE.get("access_token")
        expires_at = _TOKEN_CACHE.get("expires_at", 0.0)

        if cached_token and _now() < expires_at:
            return cached_token

        with httpx.Client(timeout=OPENSKY_TIMEOUT, follow_redirects=True) as client:
            resp = client.post(
                OPENSKY_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            token_data = resp.json()

        access_token = token_data["access_token"]
        expires_in = int(token_data.get("expires_in", 1800))

        _TOKEN_CACHE["access_token"] = access_token
        _TOKEN_CACHE["expires_at"] = _now() + max(expires_in - TOKEN_REFRESH_MARGIN, 60)

        return access_token


def _build_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "User-Agent": "OSINT-Threat-Radar/0.1 (+https://www.dfaas.it)",
    }
    token = _get_oauth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _state_to_feature(row: List[Any]) -> Optional[Dict[str, Any]]:
    """Map the OpenSky state-vector array to a GeoJSON Feature."""
    if not isinstance(row, list) or len(row) < 17:
        return None

    lon = row[5]
    lat = row[6]

    if lat is None or lon is None:
        return None

    props = {
        "icao24": row[0],
        "callsign": (row[1] or "").strip() or None,
        "origin_country": row[2],
        "time_position": row[3],
        "last_contact": row[4],
        "baro_altitude": row[7],
        "on_ground": row[8],
        "velocity": row[9],
        "true_track": row[10],
        "vertical_rate": row[11],
        "geo_altitude": row[13] if len(row) > 13 else None,
        "squawk": row[14] if len(row) > 14 else None,
        "spi": row[15] if len(row) > 15 else None,
        "position_source": row[16] if len(row) > 16 else None,
        "category": row[17] if len(row) > 17 else None,
    }

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": props,
    }


def fetch_aircraft(
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> Dict[str, Any]:
    bbox = _normalize_bbox(bbox or IT_BBOX)
    key = _bbox_key(bbox)

    hit = _get_cache(key)
    if hit and _is_cache_valid(hit):
        return hit["data"]

    min_lat, max_lat, min_lon, max_lon = bbox
    params = {
        "lamin": min_lat,
        "lamax": max_lat,
        "lomin": min_lon,
        "lomax": max_lon,
        "extended": 1,
    }

    try:
        headers = _build_headers()

        with httpx.Client(timeout=OPENSKY_TIMEOUT, follow_redirects=True) as client:
            r = client.get(OPENSKY_STATES_URL, params=params, headers=headers)

            if r.status_code == 429:
                retry_after = r.headers.get("X-Rate-Limit-Retry-After-Seconds")
                if hit:
                    stale = dict(hit["data"])
                    stale["generated_at"] = _iso_now()
                    stale["error"] = "opensky_rate_limited_stale"
                    stale["stale"] = True
                    stale["retry_after_seconds"] = retry_after
                    _set_cache(key, stale, TTL_ERROR)
                    return stale

                data = _empty("opensky_rate_limited")
                data["retry_after_seconds"] = retry_after
                _set_cache(key, data, TTL_ERROR)
                return data

            if r.status_code == 401:
                if hit:
                    stale = dict(hit["data"])
                    stale["generated_at"] = _iso_now()
                    stale["error"] = "opensky_unauthorized_stale"
                    stale["stale"] = True
                    _set_cache(key, stale, TTL_ERROR)
                    return stale

                data = _empty("opensky_unauthorized")
                _set_cache(key, data, TTL_ERROR)
                return data

            r.raise_for_status()
            raw = r.json()

        states = raw.get("states") or []
        features: List[Dict[str, Any]] = []

        for row in states:
            feature = _state_to_feature(row)
            if feature is not None:
                features.append(feature)

        data = {
            "type": "FeatureCollection",
            "generated_at": _iso_now(),
            "opensky_time": raw.get("time"),
            "count": len(features),
            "error": None,
            "stale": False,
            "rate_limit_remaining": r.headers.get("X-Rate-Limit-Remaining"),
            "retry_after_seconds": r.headers.get("X-Rate-Limit-Retry-After-Seconds"),
            "features": features,
        }

        _set_cache(key, data, TTL_OK)
        return data

    except Exception as e:
        print(f"[opensky] provider error={type(e).__name__} bbox={key}")

        if hit:
            stale = dict(hit["data"])
            stale["generated_at"] = _iso_now()
            stale["error"] = f"opensky_error_{type(e).__name__}_stale"
            stale["stale"] = True
            _set_cache(key, stale, TTL_ERROR)
            return stale

        if _is_default_italy_bbox(bbox):
            fallback = fetch_cached_aircraft_italy()
            if fallback:
                _set_cache(key, fallback, TTL_ERROR)
                return fallback

        data = _empty(f"opensky_error_{type(e).__name__}")
        _set_cache(key, data, TTL_ERROR)
        return data
