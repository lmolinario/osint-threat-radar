from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import httpx

OPENSKY_URL = "https://opensky-network.org/api/states/all"

# bbox default Europa (fallback)
EU_BBOX: Tuple[float, float, float, float] = (34.0, 72.0, -12.0, 35.0)  # (lat_min, lat_max, lon_min, lon_max)

# cache per bbox_key -> {"ts": float, "data": dict}
_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 10

# timeout (più aggressivo sul connect, più permissivo sul read)
OPENSKY_TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)
OPENSKY_HEADERS = {"User-Agent": "osint-threat-radar/1.0"}

# Client riusabile (meno handshake => meno timeout)
_CLIENT = httpx.Client(
    timeout=OPENSKY_TIMEOUT,
    headers=OPENSKY_HEADERS,
    follow_redirects=True,
    trust_env=True,   # IMPORTANT: su alcuni hosting serve usare proxy env. Mettilo True.
)


def _now() -> float:
    return time.time()


def _bbox_key(bbox: Tuple[float, float, float, float]) -> str:
    la1, la2, lo1, lo2 = bbox
    return f"{la1:.2f},{la2:.2f},{lo1:.2f},{lo2:.2f}"


def _empty(error: str) -> Dict[str, Any]:
    return {"time": None, "states": [], "error": error}


def fetch_aircraft(bbox: Optional[Tuple[float, float, float, float]] = None) -> Dict[str, Any]:
    bbox = bbox or EU_BBOX
    key = _bbox_key(bbox)

    hit = _CACHE.get(key)
    if hit and (_now() - hit["ts"]) < CACHE_TTL_SECONDS:
        return hit["data"]

    lat_min, lat_max, lon_min, lon_max = bbox
    params = {"lamin": lat_min, "lamax": lat_max, "lomin": lon_min, "lomax": lon_max}

    # retry con backoff (utile per 429/5xx/timeout)
    delays = [0.0, 0.8, 1.6]  # 3 tentativi
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

            # Rate limit / server busy: retry
            if r.status_code in (429, 502, 503, 504):
                last_err = f"opensky_http_{r.status_code}"
                continue

            # altri errori: niente retry aggressivo
            last_err = f"opensky_http_{r.status_code}"
            break

        except httpx.TimeoutException:
            last_err = "opensky_timeout"
            continue
        except httpx.HTTPError as e:
            last_err = f"opensky_http_error_{type(e).__name__}"
            continue

    # fallback: stale se disponibile
    if hit:
        stale = dict(hit["data"])
        stale["error"] = f"{last_err}_stale" if last_err else "opensky_error_stale"
        return stale

    return _empty(last_err or "opensky_error")
