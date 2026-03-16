import os
import time
import threading
from typing import Any, Dict, Optional, Tuple, List

from opensky_api import OpenSkyApi

IT_BBOX: Tuple[float, float, float, float] = (35.0, 48.0, 6.0, 19.0)

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()

TTL_OK = 10
TTL_ERROR = 5


def _bbox_key(b: Tuple[float, float, float, float]) -> str:
    return f"{b[0]:.2f},{b[1]:.2f},{b[2]:.2f},{b[3]:.2f}"


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
        "features": [],
    }


def _get_cache(key: str) -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        return _CACHE.get(key)


def _set_cache(key: str, data: Dict[str, Any], ttl: int) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = {
            "ts": _now(),
            "ttl": ttl,
            "data": data,
        }


def _is_cache_valid(hit: Dict[str, Any]) -> bool:
    return (_now() - hit["ts"]) < hit["ttl"]


def fetch_aircraft(
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> Dict[str, Any]:
    bbox = bbox or IT_BBOX
    key = _bbox_key(bbox)

    hit = _get_cache(key)
    if hit and _is_cache_valid(hit):
        return hit["data"]

    user = os.getenv("OPENSKY_USERNAME")
    pwd = os.getenv("OPENSKY_PASSWORD")

    api = OpenSkyApi(user, pwd) if (user and pwd) else OpenSkyApi()

    try:
        states = api.get_states(bbox=bbox)

        if not states or not states.states:
            data = _empty("opensky_no_states")
            _set_cache(key, data, TTL_ERROR)
            return data

        features: List[Dict[str, Any]] = []

        for s in states.states:
            if s.latitude is None or s.longitude is None:
                continue

            props = {
                "icao24": s.icao24,
                "callsign": (s.callsign or "").strip() or None,
                "origin_country": s.origin_country,
                "on_ground": s.on_ground,
                "velocity": s.velocity,
                "true_track": s.true_track,
                "baro_altitude": s.baro_altitude,
                "geo_altitude": s.geo_altitude,
                "vertical_rate": s.vertical_rate,
                "squawk": s.squawk,
                "position_source": s.position_source,
                "last_contact": s.last_contact,
                "time_position": s.time_position,
                "category": getattr(s, "category", None),
            }

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [s.longitude, s.latitude],
                },
                "properties": props,
            })

        data = {
            "type": "FeatureCollection",
            "generated_at": _iso_now(),
            "opensky_time": getattr(states, "time", None),
            "count": len(features),
            "error": None,
            "stale": False,
            "features": features,
        }

        _set_cache(key, data, TTL_OK)
        return data

    except Exception as e:
        if hit:
            stale = dict(hit["data"])
            stale["generated_at"] = _iso_now()
            stale["error"] = f"opensky_error_{type(e).__name__}_stale"
            stale["stale"] = True
            return stale

        data = _empty(f"opensky_error_{type(e).__name__}")
        _set_cache(key, data, TTL_ERROR)
        return data
