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
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
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