from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import feedparser
import httpx

from app.services.store import Event


USGS_EARTHQUAKES_DAY_GEOJSON = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
)
GDACS_RSS_URL = "https://www.gdacs.org/xml/rss.xml"


def _event_id(source: str, key: str) -> str:
    digest = hashlib.sha256(f"{source}:{key}".encode("utf-8")).hexdigest()
    return digest[:24]


def _iso_from_epoch_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _iso_from_parsed_time(value: Any) -> str:
    if value:
        try:
            return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).isoformat()


def _clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:2000]


def _magnitude_severity(magnitude: Optional[float]) -> int:
    if magnitude is None:
        return 35
    if magnitude >= 7.0:
        return 90
    if magnitude >= 6.0:
        return 75
    if magnitude >= 5.0:
        return 55
    return 40


def _gdacs_severity(text: str) -> int:
    lowered = text.lower()
    if "red" in lowered:
        return 90
    if "orange" in lowered:
        return 70
    if "green" in lowered:
        return 40
    return 50


def _infer_gdacs_type(text: str) -> str:
    lowered = text.lower()
    if "earthquake" in lowered or "tsunami" in lowered:
        return "earthquake"
    if "flood" in lowered:
        return "flood"
    if "wildfire" in lowered or "forest fire" in lowered or "fire" in lowered:
        return "wildfire"
    if "cyclone" in lowered or "hurricane" in lowered or "typhoon" in lowered or "tropical" in lowered:
        return "cyclone"
    if "volcano" in lowered or "eruption" in lowered:
        return "volcano"
    if "drought" in lowered:
        return "drought"
    if "severe weather" in lowered or "storm" in lowered:
        return "severe_weather"
    return "disaster"


def _extract_georss_point(entry: Any) -> Tuple[Optional[float], Optional[float]]:
    point = entry.get("georss_point") or entry.get("point")
    if point:
        parts = str(point).replace(",", " ").split()
        if len(parts) >= 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                pass

    lat = entry.get("geo_lat") or entry.get("lat")
    lon = entry.get("geo_long") or entry.get("lon") or entry.get("long")
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except ValueError:
            pass

    return None, None


def fetch_usgs_earthquakes(limit: int = 100) -> List[Event]:
    """
    Fetch recent M4.5+ earthquakes from the official USGS GeoJSON feed.

    The collector returns normalized Event objects so the existing /events
    endpoint and Leaflet layer can reuse the same rendering pipeline.
    """
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(USGS_EARTHQUAKES_DAY_GEOJSON)
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
    except Exception as exc:
        print(f"[earth_intel] usgs fetch error: {exc}")
        return []

    events: List[Event] = []
    for feature in (data.get("features") or [])[:limit]:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        depth_km = coords[2] if len(coords) > 2 else None
        magnitude = props.get("mag")
        try:
            magnitude = float(magnitude) if magnitude is not None else None
        except (TypeError, ValueError):
            magnitude = None

        place = props.get("place") or "Unknown location"
        title = props.get("title") or f"M{magnitude or 'n/a'} earthquake - {place}"
        url = props.get("url") or ""
        ts = _iso_from_epoch_ms(props.get("time"))
        alert = props.get("alert") or "n/a"
        event_key = feature.get("id") or url or title

        depth_text = f" Depth: {depth_km:.1f} km." if isinstance(depth_km, (int, float)) else ""
        summary = f"USGS earthquake event. Magnitude: {magnitude or 'n/a'}.{depth_text} Alert: {alert}."

        events.append(
            Event(
                id=_event_id("usgs", str(event_key)),
                source="usgs",
                type="earthquake",
                ts=ts,
                title=title,
                summary=summary,
                url=url,
                severity=_magnitude_severity(magnitude),
                confidence=0.9,
                tags=["earth", "earthquake", "usgs", "geojson"],
                lat=float(lat),
                lon=float(lon),
                raw={"provider": "USGS", "magnitude": magnitude, "depth_km": depth_km, "alert": alert},
            )
        )

    events.sort(key=lambda event: event.ts, reverse=True)
    return events


def fetch_gdacs_alerts(max_items: int = 50) -> List[Event]:
    """
    Fetch GDACS multi-hazard disaster alerts from the public RSS feed.

    GDACS entries may not always include coordinates. Events without a valid
    point are still stored and remain searchable in the sidebar.
    """
    try:
        parsed = feedparser.parse(GDACS_RSS_URL)
    except Exception as exc:
        print(f"[earth_intel] gdacs fetch error: {exc}")
        return []

    events: List[Event] = []
    for entry in parsed.entries[:max_items]:
        title = (entry.get("title") or "GDACS alert").strip()
        link = (entry.get("link") or "").strip()
        summary = _clean_html(entry.get("summary") or entry.get("description") or "")
        ts = _iso_from_parsed_time(entry.get("published_parsed") or entry.get("updated_parsed"))
        lat, lon = _extract_georss_point(entry)
        text = f"{title} {summary}"
        event_type = _infer_gdacs_type(text)
        event_key = entry.get("id") or entry.get("guid") or link or title

        events.append(
            Event(
                id=_event_id("gdacs", str(event_key)),
                source="gdacs",
                type=event_type,
                ts=ts,
                title=title,
                summary=summary,
                url=link,
                severity=_gdacs_severity(text),
                confidence=0.85,
                tags=["earth", "disaster", "gdacs", event_type],
                lat=lat,
                lon=lon,
                raw={"provider": "GDACS", "feed_url": GDACS_RSS_URL},
            )
        )

    events.sort(key=lambda event: event.ts, reverse=True)
    return events


def fetch_earth_intel_events() -> List[Event]:
    """
    Aggregate Earth/disaster intelligence sources for the radar MVP.
    """
    events: List[Event] = []
    events.extend(fetch_usgs_earthquakes())
    events.extend(fetch_gdacs_alerts())
    events.sort(key=lambda event: event.ts, reverse=True)
    return events
