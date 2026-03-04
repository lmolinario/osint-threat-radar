from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import List

import feedparser
from app.services.georesolver import resolve_latlon
from app.services.store import Event


DEFAULT_FEEDS = [
    # puoi aggiungere/variare fonti dopo; per ora mettiamo feed generici
    "https://www.reddit.com/r/netsec/.rss",
    "https://www.ansa.it/sito/ansait_rss.xml",
]


def _event_id(source: str, key: str) -> str:
    h = hashlib.sha256(f"{source}:{key}".encode("utf-8")).hexdigest()
    return h[:24]


def _to_iso(entry) -> str:
    # best-effort: published_parsed -> iso
    if getattr(entry, "published_parsed", None):
        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    return datetime.now(timezone.utc).isoformat()


def fetch_rss_events(feeds: List[str] | None = None, max_per_feed: int = 30) -> List[Event]:
    feeds = feeds or DEFAULT_FEEDS
    out: List[Event] = []

    for url in feeds:
        parsed = feedparser.parse(url)
        source = "rss"

        for entry in parsed.entries[:max_per_feed]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            ts = _to_iso(entry)

            key = link or title or ts
            eid = _event_id(source, key)
            loc = resolve_latlon(title)

            lat, lon = (loc if loc else (None, None))

            out.append(
                Event(
                    id=eid,
                    source=source,
                    type="news",
                    ts=ts,
                    title=title or "(no title)",
                    summary=(summary or "")[:2000],
                    url=link,
                    severity=25,
                    confidence=0.55,
                    tags=["rss"],
                    raw={"feed_url": url},
                    lat=lat,
                    lon=lon,
                )
            )

    # ordina recenti prima
    out.sort(key=lambda e: e.ts, reverse=True)
    return out