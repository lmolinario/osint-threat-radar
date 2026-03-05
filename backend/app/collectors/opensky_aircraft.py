from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import httpx

OPENSKY_URL = "https://opensky-network.org/api/states/all"

EU_BBOX: Tuple[float, float, float, float] = (34.0, 72.0, -12.0, 35.0)   # Europa
IT_BBOX: Tuple[float, float, float, float] = (35.0, 48.0, 6.0, 19.0)     # Italia (default consigliato)

_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 10

OPENSKY_TIMEOUT = httpx.Timeout(connect=6.0, read=20.0, write=6.0, pool=6.0)
OPENSKY_HEADERS = {"User-Agent": "osint-threat-radar/1.0"}

_CLIENT = httpx.Client(
    timeout=OPENSKY_TIMEOUT,
    headers=OPENSKY_HEADERS,
    follow_redirects=True,
    trust_env=True,
)


def _now() -> float:
    return time.time()


def _bbox_key(bbox: Tuple[float, float, float, float]) -> str:
    la1, la2, lo1, lo2 = bbox
    return f"{la1:.2f},{la2:.2f},{lo1:.2f},{lo2:.2f}"


def _empty(error: str) -> Dict[str, Any]:
    return {"time": None, "states": [], "error": error}


def fetch_aircraft(bbox: Optional[Tuple[float, float, float, float]] = None) -> Dict[str, Any]:
    bbox = bbox or IT_BBOX
    key = _bbox_key(bbox)

    hit = _CACHE.get(key)
    if hit and (_now() - hit["ts"]) < CACHE_TTL_SECONDS:
        return hit["data"]

    lat_min, lat_max, lon_min, lon_max = bbox
    params = {"lamin": lat_min, "lamax": lat_max, "lomin": lon_min, "lomax": lon_max}

    delays = [0.0, 0.8, 1.6]  # retry con backoff
    last_err: Optional[str] = None

    for d in delays:
        if d:
            time.sleep(d)

        try:
            r = _CLIENT.get(OPENSKY_URL, params=params)

            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    last_err = "opensky_invalid_json"
                    continue

                if not isinstance(data, dict):
                    last_err = "opensky_bad_payload"
                    continue

                data.setdefault("time", None)
                data.setdefault("states", [])

                _CACHE[key] = {"ts": _now(), "data": data}
                return data

            if r.status_code in (429, 502, 503, 504):
                last_err = f"opensky_http_{r.status_code}"
                continue

            last_err = f"opensky_http_{r.status_code}"
            break

        except httpx.TimeoutException:
            last_err = "opensky_timeout"
            continue
        except httpx.HTTPError as e:
            last_err = f"opensky_http_error_{type(e).__name__}"
            continue

    if hit:
        stale = dict(hit["data"])
        stale["error"] = f"{last_err}_stale" if last_err else "opensky_error_stale"
        return stale

    return _empty(last_err or "opensky_error")
