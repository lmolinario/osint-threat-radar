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

    The OpenSky collector already returns normalized GeoJSON features. This
    endpoint adapts property names for the frontend while preserving collector
    metadata such as errors, stale responses and rate-limit hints.
    """
    bbox = None
    if None not in (lamin, lamax, lomin, lomax):
        bbox = (lamin, lamax, lomin, lomax)

    raw = fetch_aircraft(bbox=bbox)
    raw_features = raw.get("features") or []

    features = []
    for feature in raw_features:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        coordinates = geometry.get("coordinates") or []

        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue

        icao24 = properties.get("icao24") or feature.get("id")
        callsign = (properties.get("callsign") or "").strip() if properties.get("callsign") else ""

        features.append(
            {
                "type": "Feature",
                "id": icao24,
                "geometry": geometry,
                "properties": {
                    "icao24": icao24,
                    "callsign": callsign,
                    "country": properties.get("origin_country"),
                    "origin_country": properties.get("origin_country"),
                    "time_position": properties.get("time_position"),
                    "last_contact": properties.get("last_contact"),
                    "baro_altitude": properties.get("baro_altitude"),
                    "on_ground": properties.get("on_ground"),
                    "velocity": properties.get("velocity"),
                    "track": properties.get("true_track"),
                    "true_track": properties.get("true_track"),
                    "vertical_rate": properties.get("vertical_rate"),
                    "geo_altitude": properties.get("geo_altitude"),
                    "squawk": properties.get("squawk"),
                    "spi": properties.get("spi"),
                    "position_source": properties.get("position_source"),
                    "category": properties.get("category"),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "generated_at": raw.get("generated_at") or now_iso(),
        "opensky_time": raw.get("opensky_time"),
        "count": len(features),
        "error": raw.get("error"),
        "stale": raw.get("stale"),
        "rate_limit_remaining": raw.get("rate_limit_remaining"),
        "retry_after_seconds": raw.get("retry_after_seconds"),
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


def _empty_satellite_response(group: str, limit: int, error: str) -> Dict:
    return {
        "generated_at": now_iso(),
        "group": group,
        "count": 0,
        "total_visible": 0,
        "total_available": 0,
        "truncated": False,
        "limit": limit,
        "error": error,
        "items": [],
    }


@app.get("/satellites")
def satellites(
    group: str = Query("stations"),
    lamin: float | None = Query(default=None),
    lamax: float | None = Query(default=None),
    lomin: float | None = Query(default=None),
    lomax: float | None = Query(default=None),
    limit: int = Query(default=1500, ge=1, le=20000),
) -> Dict:
    try:
        tles = tle_cache.get(group=group)
    except Exception as exc:
        return _empty_satellite_response(group, limit, f"celestrak_error_{type(exc).__name__}")

    now = datetime.now(timezone.utc)
    jd, fr = jday(
        now.year,
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second + now.microsecond / 1e6,
    )

    has_bbox = None not in (lamin, lamax, lomin, lomax)
    total_available = len(tles)
    items: List[Dict] = []
    total_visible = 0

    # Without a viewport filter, avoid propagating very large constellations
    # just to discard most records later. This keeps Starlink queries small
    # and predictable while still reporting the total catalog size.
    iterable = tles if has_bbox else tles[:limit]

    for tle in iterable:
        try:
            sat = Satrec.twoline2rv(tle["line1"], tle["line2"])
            error_code, position, velocity = sat.sgp4(jd, fr)
            if error_code != 0 or position is None:
                continue

            lat, lon, alt_km = eci_to_geodetic_simple(position[0], position[1], position[2])

            if has_bbox:
                if not (lamin <= lat <= lamax and lomin <= lon <= lomax):
                    continue

            total_visible += 1
            if len(items) >= limit:
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
        except Exception:
            continue

    if not has_bbox:
        total_visible = total_available

    return {
        "generated_at": now_iso(),
        "group": group,
        "count": len(items),
        "total_visible": total_visible,
        "total_available": total_available,
        "truncated": total_visible > len(items),
        "limit": limit,
        "error": None,
        "items": items,
    }
