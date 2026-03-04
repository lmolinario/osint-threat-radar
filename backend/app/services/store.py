from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional


@dataclass
class Event:
    id: str
    source: str
    type: str
    ts: str  # ISO8601
    title: str
    summary: str = ""
    url: str = ""
    severity: int = 20
    confidence: float = 0.6
    tags: List[str] = field(default_factory=list)
    lat: Optional[float] = None
    lon: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class InMemoryEventStore:
    """
    MVP store: holds latest events in memory.
    Replace later with Postgres/PostGIS.
    """
    def __init__(self, max_events: int = 2000) -> None:
        self._max = max_events
        self._lock = Lock()
        self._events: List[Event] = []

    def upsert_many(self, events: List[Event]) -> int:
        if not events:
            return 0
        with self._lock:
            existing_ids = {e.id for e in self._events}
            new_events = [e for e in events if e.id not in existing_ids]
            if not new_events:
                return 0
            self._events.extend(new_events)
            # sort by time desc
            self._events.sort(key=lambda e: e.ts, reverse=True)
            # cap
            if len(self._events) > self._max:
                self._events = self._events[: self._max]
            return len(new_events)

    def list(
        self,
        source: Optional[str] = None,
        type_: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 200,
    ) -> List[Event]:
        with self._lock:
            items = list(self._events)

        if source:
            items = [e for e in items if e.source == source]
        if type_:
            items = [e for e in items if e.type == type_]
        if q:
            ql = q.lower()
            items = [e for e in items if ql in e.title.lower() or ql in (e.summary or "").lower()]

        return items[: max(1, min(limit, 2000))]


STORE = InMemoryEventStore()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()