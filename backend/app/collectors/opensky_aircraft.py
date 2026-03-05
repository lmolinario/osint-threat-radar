import os
import time
from typing import Any, Dict, Optional, Tuple, List

from opensky_api import OpenSkyApi

IT_BBOX: Tuple[float, float, float, float] = (35.0, 48.0, 6.0, 19.0)

_CACHE: Dict[str, Dict[str, Any]] = {}
TTL = 10


def _bbox_key(b: Tuple[float, float, float, float]) -> str:
    return f"{b[0]:.2f},{b[1]:.2f},{b[2]:.2f},{b[3]:.2f}"


def _now() -> float:
    return time.time()


def _empty(error: str) -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "opensky_time": None,
        "count": 0,
        "error": error,
        "features": [],
    }


def fetch_aircraft_geojson(bbox: Optional[Tuple[float, float, float, float]] = None) -> Dict[str, Any]:
    bbox = bbox or IT_BBOX
    key = _bbox_key(bbox)

    hit = _CACHE.get(key)
    if hit and (_now() - hit["ts"]) < TTL:
        return hit["data"]

    user = os.getenv("OPENSKY_USERNAME")
    pwd = os.getenv("OPENSKY_PASSWORD")

    api = OpenSkyApi(user, pwd) if (user and pwd) else OpenSkyApi()

    try:
        # bbox = (min_lat, max_lat, min_lon, max_lon)
        states = api.get_states(bbox=bbox)
        if not states or not states.states:
            data = _empty("opensky_no_states")
            _CACHE[key] = {"ts": _now(), "data": data}
            return data

        features: List[Dict[str, Any]] = []
        for s in states.states:
            # s.latitude / s.longitude possono essere None
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
                "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
                "properties": props,
            })

        data = {
            "type": "FeatureCollection",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "opensky_time": getattr(states, "time", None),
            "count": len(features),
            "error": None,
            "features": features,
        }

        _CACHE[key] = {"ts": _now(), "data": data}
        return data

    except Exception as e:
        # fallback su stale se esiste
        if hit:
            stale = dict(hit["data"])
            stale["error"] = f"opensky_error_{type(e).__name__}_stale"
            return stale
        return _empty(f"opensky_error_{type(e).__name__}")
