from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import httpx

OPENSKY_URL = "https://opensky-network.org/api/states/all"

# Cache per bbox (chiave stringa) -> {"ts": float, "data": dict}
_CACHE: Dict[str, Dict[str, Any]] = {}

# TTL cache: 10s (rate limit friendly)
CACHE_TTL_SECONDS = 10

# Bbox default Europa (fallback)
EU_BBOX = (34.0, 72.0, -12.0, 35.0)  # (lat_min, lat_max, lon_min, lon_max)

# Timeout esplicito (evita hang e 500 su Render/proxy)
OPENSKY_TIMEOUT = httpx.Timeout(connect=8.0, read=12.0, write=8.0, pool=8.0)

# Header UA “pulito” (alcuni edge/proxy apprezzano)
OPENSKY_HEADERS = {"User-Agent": "osint-threat-radar/1.0"}


def _now() -> float:
    return time.time()


def _bbox_key(bbox: Tuple[float, float, float, float]) -> str:
    # riduce "esplosione" chiavi: arrotonda a 2 decimali (~1 km)
    la1, la2, lo1, lo2 = bbox
    return f"{la1:.2f},{la2:.2f},{lo1:.2f},{lo2:.2f}"


def _empty(error: str) -> Dict[str, Any]:
    # Payload “safe”: compatibile con OpenSky (time/states)
    return {"time": None, "states": [], "error": error}

import time as _t
import httpx

OPENSKY_TIMEOUT = httpx.Timeout(connect=8.0, read=12.0, write=8.0, pool=8.0)
OPENSKY_HEADERS = {"User-Agent": "osint-threat-radar/1.0"}

def fetch_aircraft(bbox=None):
    bbox = bbox or EU_BBOX
    key = _bbox_key(bbox)

    hit = _CACHE.get(key)
    if hit and (_now() - hit["ts"]) < CACHE_TTL_SECONDS:
        return hit["data"]

    lat_min, lat_max, lon_min, lon_max = bbox
    params = {"lamin": lat_min, "lamax": lat_max, "lomin": lon_min, "lomax": lon_max}

    def _request():
        with httpx.Client(
            timeout=OPENSKY_TIMEOUT,
            headers=OPENSKY_HEADERS,
            trust_env=False,   # evita proxy env “strani”
        ) as client:
            return client.get(OPENSKY_URL, params=params)

    try:
        try:
            r = _request()
        except httpx.TimeoutException:
            _t.sleep(0.4)
            r = _request()

        if r.status_code != 200:
            return _empty(f"opensky_http_{r.status_code}")

        try:
            data = r.json()
        except ValueError:
            return _empty("opensky_invalid_json")

        if not isinstance(data, dict):
            return _empty("opensky_bad_payload")

        data.setdefault("time", None)
        data.setdefault("states", [])

        # Cache solo su success
        _CACHE[key] = {"ts": _now(), "data": data}
        return data

    except httpx.TimeoutException:
        # stale cache fallback
        if hit:
            stale = dict(hit["data"])
            stale["error"] = "opensky_timeout_stale"
            return stale
        return _empty("opensky_timeout")

    except httpx.HTTPError as e:
        if hit:
            stale = dict(hit["data"])
            stale["error"] = f"opensky_http_error_{type(e).__name__}_stale"
            return stale
        return _empty(f"opensky_http_error_{type(e).__name__}")