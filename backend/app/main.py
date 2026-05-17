from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sgp4.api import Satrec, jday

from app.collectors.celestrak_satellites import TLECache
from app.collectors.earth_intel_collector import fetch_earth_intel_events
from app.collectors.opensky_aircraft import fetch_aircraft
from app.collectors.rss_collector import fetch_rss_events
from app.services.store import STORE, now_iso


app = FastAPI(title="OSINT Threat Radar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "https://dfaas.it",
        "https://www.dfaas.it",
        "https://lmolinario.github.io",
        "https://osint-threat-radar.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


tle_cache = TLECache(ttl_seconds=900)  # 15 minutes


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
    Return normalized events as a GeoJSON FeatureCollection.
    """
    items = STORE.list(source=source, type_=type, q=q, limit=limit)

    features = []
    for event in items:
        geom = None
        if event.lat is not None and event.lon is not None:
            geom = {"type": "Point", "coordinates": [event.lon, event.lat]}

        features.append(
            {
                "type": "Feature",
                "id": event.id,
                "geometry": geom,
                "properties": {
                    "source": event.source,
                    "type": event.type,
                    "ts": event.ts,
                    "title": event.title,
                    "summary": event.summary,
                    "url": event.url,
                    "severity": event.severity,
                    "confidence": event.confidence,
                    "tags": event.tags,
                },
            }
        )

    return {"type": "FeatureCollection", "generated_at": now_iso(), "features": features}


@app.post("/refresh/earth-intel")
def refresh_earth_intel():
    """
    Manually refresh Earth/disaster intelligence events.

    This endpoint is useful after deployment or during demos because the MVP
    store is still in memory and is repopulated at startup/scheduler runtime.
    """
    events = fetch_earth_intel_events()
    inserted = STORE.upsert_many(events)
    return {
        "generated_at": now_iso(),
        "fetched": len(events),
        "inserted": inserted,
        "sources": ["usgs", "gdacs"],
    }


@app.get("/aircraft")
def aircraft(
    lamin: Optional[float] = Query(default=None),
    lamax: Optional[float] = Query(default=None),
    lomin: Optional[float] = Query(default=None),
    lomax: Optional[float] = Query(default=None),
):
    """
    Live aircraft layer from OpenSky, optionally filtered by viewport bbox.
    """
    bbox = None
    if None not in (lamin, lamax, lomin, lomax):
        bbox = (lamin, lamax, lomin, lomax)

    raw = fetch_aircraft(bbox=bbox)
    states = raw.get("states") or []
    ts = raw.get("time")

    features = []
    for state in states:
        icao24 = state[0]
        callsign = (state[1] or "").strip() if len(state) > 1 else ""
        country = state[2] if len(state) > 2 else ""
        lon = state[5] if len(state) > 5 else None
        lat = state[6] if len(state) > 6 else None
        on_ground = state[8] if len(state) > 8 else None
        velocity = state[9] if len(state) > 9 else None
        track = state[10] if len(state) > 10 else None
        geo_alt = state[13] if len(state) > 13 else None

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
        "error": raw.get("error"),
        "features": features,
    }


async def _rss_scheduler() -> None:
    while True:
        try:
            inserted = STORE.upsert_many(fetch_rss_events())
            if inserted:
                print(f"[rss_scheduler] inserted={inserted}")
        except Exception as exc:
            print(f"[rss_scheduler] error: {exc}")
        await asyncio.sleep(60)


async def _earth_intel_scheduler() -> None:
    while True:
        try:
            inserted = STORE.upsert_many(fetch_earth_intel_events())
            if inserted:
                print(f"[earth_intel_scheduler] inserted={inserted}")
        except Exception as exc:
            print(f"[earth_intel_scheduler] error: {exc}")
        await asyncio.sleep(300)


@app.on_event("startup")
async def startup_event():
    try:
        STORE.upsert_many(fetch_rss_events())
    except Exception as exc:
        print(f"[startup] rss fetch error: {exc}")

    try:
        STORE.upsert_many(fetch_earth_intel_events())
    except Exception as exc:
        print(f"[startup] earth intel fetch error: {exc}")

    asyncio.create_task(_rss_scheduler())
    asyncio.create_task(_earth_intel_scheduler())


def eci_to_geodetic_simple(x_km: float, y_km: float, z_km: float):
    """
    Approximate ECI-to-geodetic conversion for the MVP satellite layer.
    """
    import math

    radius_km = math.sqrt(x_km * x_km + y_km * y_km + z_km * z_km)
    lat = math.degrees(math.asin(z_km / radius_km))
    lon = math.degrees(math.atan2(y_km, x_km))
    alt = radius_km - 6371.0
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
        now.year,
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second + now.microsecond / 1e6,
    )

    items: List[Dict] = []
    for tle in tles:
        sat = Satrec.twoline2rv(tle["line1"], tle["line2"])
        error_code, position, velocity = sat.sgp4(jd, fr)
        if error_code != 0 or position is None:
            continue

        lat, lon, alt_km = eci_to_geodetic_simple(position[0], position[1], position[2])

        if None not in (lamin, lamax, lomin, lomax):
            if not (lamin <= lat <= lamax and lomin <= lon <= lomax):
                continue

        speed_kms = (velocity[0] ** 2 + velocity[1] ** 2 + velocity[2] ** 2) ** 0.5

        items.append(
            {
                "name": tle["name"],
                "norad_id": sat.satnum,
                "lat": lat,
                "lon": lon,
                "alt_km": alt_km,
                "speed_kms": speed_kms,
            }
        )

    return {
        "generated_at": now_iso(),
        "group": group,
        "count": len(items),
        "items": items,
    }
