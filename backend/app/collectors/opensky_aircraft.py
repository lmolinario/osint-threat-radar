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


def fetch_aircraft(bbox: Optional[Tuple[float, float, float, float]] = None) -> Dict[str, Any]:
    """
    Fetch aircraft states from OpenSky, optionally filtered by bbox:
      bbox = (lat_min, lat_max, lon_min, lon_max)

    Cached per-bbox for CACHE_TTL_SECONDS (solo su success).
    """
    bbox = bbox or EU_BBOX
    key = _bbox_key(bbox)

    hit = _CACHE.get(key)
    if hit and (_now() - hit["ts"]) < CACHE_TTL_SECONDS:
        return hit["data"]

    lat_min, lat_max, lon_min, lon_max = bbox

    # OpenSky expects lamin/lamax/lomin/lomax
    params = {
        "lamin": lat_min,
        "lamax": lat_max,
        "lomin": lon_min,
        "lomax": lon_max,
    }

    try:
        with httpx.Client(timeout=OPENSKY_TIMEOUT, headers=OPENSKY_HEADERS) as client:
            r = client.get(OPENSKY_URL, params=params)

        if r.status_code != 200:
            return _empty(f"opensky_http_{r.status_code}")

        try:
            data = r.json()
        except ValueError:
            return _empty("opensky_invalid_json")

        if not isinstance(data, dict):
            return _empty("opensky_bad_payload")

        # Normalizza campi minimi
        data.setdefault("time", None)
        data.setdefault("states", [])

        # Cache SOLO su risposta valida (evita cache di timeout/errori)
        _CACHE[key] = {"ts": _now(), "data": data}
        return data

    except httpx.TimeoutException:
        return _empty("opensky_timeout")
    except httpx.HTTPError as e:
        return _empty(f"opensky_http_error_{type(e).__name__}")
    except Exception:
        # ultima rete di sicurezza: mai 500 per collector
        return _empty("opensky_unexpected_error")