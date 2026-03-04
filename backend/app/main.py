from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI, Query

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