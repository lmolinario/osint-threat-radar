from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable, List

import feedparser

from app.services.georesolver import resolve_latlon
from app.services.store import Event


MILITARY_FEEDS = [
    "https://www.ansa.it/sito/ansait_rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]

MILITARY_KEYWORDS = [
    "air strike",
    "airstrike",
    "attack",
    "attacco",
    "ceasefire",
    "conflict",
    "defence",
    "defense",
    "drone",
    "droni",
    "esercito",
    "fighter jet",
    "guerra",
    "incursion",
    "invasion",
    "military",
    "missile",
    "naval",
    "nato",
    "offensive",
    "raid",
    "rocket",
    "strike",
    "troops",
    "war",
    "weapon",
]

SEVERE_KEYWORDS = [
    "air strike",
    "airstrike",
    "ballistic",
    "bombard",
    "dead",
    "killed",
    "missile",
    "strikes",
    "war",
]

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(value: str) -> str:
    value = _TAG_RE.sub(" ", value or "")
    return re.sub(r"\s+", " ", value).strip()[:2000]


def _event_id(source: str, key: str) -> str:
    digest = hashlib.sha256(f"{source}:{key}".encode("utf-8")).hexdigest()
    return digest[:24]


def _to_iso(entry) -> str:
    published = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if published:
        try:
            return datetime(*published[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).isoformat()


def _contains_keyword(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _severity(text: str) -> int:
    lowered = text.lower()
    if _contains_keyword(lowered, SEVERE_KEYWORDS):
        return 75
    return 55


def fetch_military_events(feeds: List[str] | None = None, max_per_feed: int = 40) -> List[Event]:
    """
    Fetch OSINT military/conflict-related events from public RSS feeds.

    This is a lightweight MVP collector. It intentionally uses keyword
    filtering and explicit tags rather than making authoritative claims about
    events. Items remain linked to their original sources for verification.
    """
    feeds = feeds or MILITARY_FEEDS
    events: List[Event] = []

    for feed_url in feeds:
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries[:max_per_feed]:
            title = (getattr(entry, "title", "") or "").strip()
            link = (getattr(entry, "link", "") or "").strip()
            summary = _clean_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
            text = f"{title} {summary}"

            if not _contains_keyword(text, MILITARY_KEYWORDS):
                continue

            ts = _to_iso(entry)
            key = link or title or ts
            loc = resolve_latlon(text)
            lat, lon = (loc if loc else (None, None))

            events.append(
                Event(
                    id=_event_id("military_osint", key),
                    source="military_osint",
                    type="military_event",
                    ts=ts,
                    title=title or "Military OSINT event",
                    summary=summary,
                    url=link,
                    severity=_severity(text),
                    confidence=0.6,
                    tags=["military", "osint", "rss"],
                    raw={"feed_url": feed_url},
                    lat=lat,
                    lon=lon,
                )
            )

    events.sort(key=lambda event: event.ts, reverse=True)
    return events
