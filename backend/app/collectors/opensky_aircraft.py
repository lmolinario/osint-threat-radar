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


def _now() -> float:
    return time.time()


def _bbox_key(bbox: Tuple[float, float, float, float]) -> str:
    # riduce "esplosione" chiavi: arrotonda a 2 decimali (~1 km)
    la1, la2, lo1, lo2 = bbox
    return f"{la1:.2f},{la2:.2f},{lo1:.2f},{lo2:.2f}"


def fetch_aircraft(bbox: Optional[Tuple[float, float, float, float]] = None) -> Dict[str, Any]:
    """
    Fetch aircraft states from OpenSky, optionally filtered by bbox:
      bbox = (lat_min, lat_max, lon_min, lon_max)

    Cached per-bbox for CACHE_TTL_SECONDS.
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

    with httpx.Client(timeout=15.0) as client:
        r = client.get(OPENSKY_URL, params=params)
        r.raise_for_status()
        data = r.json()

    _CACHE[key] = {"ts": _now(), "data": data}
    return data