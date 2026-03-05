from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI, Query


from typing import Optional

from app.collectors.opensky_aircraft import fetch_aircraft

from app.collectors.rss_collector import fetch_rss_events
from app.services.store import STORE, now_iso


app = FastAPI(title="OSINT Threat Radar")



from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "https://dfaas.it",
        "https://www.dfaas.it",
        "https://osint-threat-radar.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "OSINT Threat Radar API"}



@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/events")
def list_events(
    source: Optional[str] = None,
    type: Optional[str] = None,  # noqa: A002
    q: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=2000),
):
    """
    Returns events as GeoJSON FeatureCollection (lat/lon optional).
    """
    items = STORE.list(source=source, type_=type, q=q, limit=limit)

    features = []
    for e in items:
        geom = None
        if e.lat is not None and e.lon is not None:
            geom = {"type": "Point", "coordinates": [e.lon, e.lat]}

        features.append(
            {
                "type": "Feature",
                "id": e.id,
                "geometry": geom,
                "properties": {
                    "source": e.source,
                    "type": e.type,
                    "ts": e.ts,
                    "title": e.title,
                    "summary": e.summary,
                    "url": e.url,
                    "severity": e.severity,
                    "confidence": e.confidence,
                    "tags": e.tags,
                },
            }
        )

    return {"type": "FeatureCollection", "generated_at": now_iso(), "features": features}




@app.get("/aircraft")
def aircraft(
    lamin: Optional[float] = Query(default=None),
    lamax: Optional[float] = Query(default=None),
    lomin: Optional[float] = Query(default=None),
    lomax: Optional[float] = Query(default=None),
):
    """
    Live aircraft layer (OpenSky) filtered by bbox (viewport).
    Params:
      lamin, lamax, lomin, lomax
    """
    bbox = None
    if None not in (lamin, lamax, lomin, lomax):
        bbox = (lamin, lamax, lomin, lomax)

    raw = fetch_aircraft(bbox=bbox)
    states = raw.get("states") or []
    ts = raw.get("time")

    features = []
    for s in states:
        icao24 = s[0]
        callsign = (s[1] or "").strip() if len(s) > 1 else ""
        country = s[2] if len(s) > 2 else ""
        lon = s[5] if len(s) > 5 else None
        lat = s[6] if len(s) > 6 else None
        on_ground = s[8] if len(s) > 8 else None
        velocity = s[9] if len(s) > 9 else None
        track = s[10] if len(s) > 10 else None
        geo_alt = s[13] if len(s) > 13 else None

        if lat is None or lon is None:
            continue

        features.append(
            {
                "type": "Feature",
                "id": icao24,
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "callsign": callsign,
                    "country": country,
                    "on_ground": on_ground,
                    "velocity": velocity,
                    "track": track,
                    "geo_altitude": geo_alt,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "generated_at": now_iso(),
        "opensky_time": ts,
        "count": len(features),
        "error": raw.get("error"),          # <-- QUESTA è la differenza
        "features": features,
    }

async def _rss_scheduler() -> None:
    # ogni 60s aggiorna eventi RSS
    while True:
        try:
            events = fetch_rss_events()
            STORE.upsert_many(events)
        except Exception as exc:
            # log minimale (poi metteremo logging serio)
            print(f"[rss_scheduler] error: {exc}")
        await asyncio.sleep(60)


@app.on_event("startup")
async def startup_event():
    # primo fetch subito
    try:
        STORE.upsert_many(fetch_rss_events())
    except Exception as exc:
        print(f"[startup] rss fetch error: {exc}")

    # avvia scheduler
    asyncio.create_task(_rss_scheduler())





from datetime import datetime, timezone
from typing import List, Dict

from sgp4.api import Satrec, jday

from app.collectors.celestrak_satellites import TLECache

tle_cache = TLECache(ttl_seconds=900)  # 15 minuti


def eci_to_geodetic_simple(x_km: float, y_km: float, z_km: float):
    """
    Conversione ECI->lat/lon approssimata (MVP).
    """
    import math
    r = math.sqrt(x_km * x_km + y_km * y_km + z_km * z_km)
    lat = math.degrees(math.asin(z_km / r))
    lon = math.degrees(math.atan2(y_km, x_km))
    alt = r - 6371.0
    return lat, lon, alt



@app.get("/satellites")
def satellites(
    group: str = Query("stations"),
    lamin: float | None = Query(default=None),
    lamax: float | None = Query(default=None),
    lomin: float | None = Query(default=None),
    lomax: float | None = Query(default=None),
) -> Dict:
    tles = tle_cache.get(group=group)

    now = datetime.now(timezone.utc)
    jd, fr = jday(
        now.year, now.month, now.day,
        now.hour, now.minute,
        now.second + now.microsecond / 1e6
    )

    items: List[Dict] = []
    for t in tles:
        sat = Satrec.twoline2rv(t["line1"], t["line2"])
        e, r, v = sat.sgp4(jd, fr)
        if e != 0 or r is None:
            continue

        lat, lon, alt_km = eci_to_geodetic_simple(r[0], r[1], r[2])



        # filtro bbox (viewport)
        if None not in (lamin, lamax, lomin, lomax):
            if not (lamin <= lat <= lamax and lomin <= lon <= lomax):
                continue

        speed_kms = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5

        items.append({
            "name": t["name"],
            "norad_id": sat.satnum,
            "lat": lat,
            "lon": lon,
            "alt_km": alt_km,
            "speed_kms": speed_kms
        })

    return {
        "generated_at": now_iso(),
        "group": group,
        "count": len(items),
        "items": items,
    }