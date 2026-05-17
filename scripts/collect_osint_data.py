#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Collect open-source geospatial intelligence data and store it as small JSON snapshots.

The script is designed for GitHub Actions:
- fetches aircraft state vectors over Italy from OpenSky;
- fetches public satellite TLE/GP data from CelesTrak;
- fetches selected public RSS/Atom feeds;
- writes latest snapshots for dashboards;
- writes timestamped history snapshots for lightweight versioned storage;
- applies simple retention to avoid uncontrolled repository growth.

No secret is required for the default collectors. Optional API-specific collectors can be
added later through GitHub Actions secrets.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
LATEST_DIR = DATA_DIR / "latest"
HISTORY_DIR = DATA_DIR / "history"

REQUEST_TIMEOUT_SECONDS = 25
RETENTION_DAYS = 14


@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str
    category: str


RSS_FEEDS: tuple[FeedConfig, ...] = (
    FeedConfig(
        name="usgs_significant_earthquakes",
        url="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.atom",
        category="earthquake",
    ),
    FeedConfig(
        name="gdacs_alerts",
        url="https://www.gdacs.org/xml/rss.xml",
        category="disaster_alert",
    ),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def request_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def request_text(url: str) -> str:
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def collect_aircraft_italy(generated_at: str) -> dict[str, Any]:
    """Collect aircraft over an approximate Italy bounding box from OpenSky."""

    url = "https://opensky-network.org/api/states/all"
    params = {
        "lamin": 35.0,
        "lamax": 47.8,
        "lomin": 6.0,
        "lomax": 19.0,
    }

    try:
        raw = request_json(url, params=params)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        return {
            "type": "FeatureCollection",
            "source": "opensky",
            "dataset": "aircraft_italy",
            "generated_at": generated_at,
            "count": 0,
            "error": "http_error",
            "status_code": status_code,
            "features": [],
        }
    except requests.RequestException as exc:
        return {
            "type": "FeatureCollection",
            "source": "opensky",
            "dataset": "aircraft_italy",
            "generated_at": generated_at,
            "count": 0,
            "error": exc.__class__.__name__,
            "features": [],
        }

    features: list[dict[str, Any]] = []
    for state in raw.get("states") or []:
        longitude = state[5]
        latitude = state[6]
        if longitude is None or latitude is None:
            continue

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
                "properties": {
                    "icao24": state[0],
                    "callsign": (state[1] or "").strip() or None,
                    "origin_country": state[2],
                    "time_position": state[3],
                    "last_contact": state[4],
                    "baro_altitude": state[7],
                    "on_ground": state[8],
                    "velocity": state[9],
                    "true_track": state[10],
                    "vertical_rate": state[11],
                    "geo_altitude": state[13],
                    "squawk": state[14],
                    "spi": state[15],
                    "position_source": state[16],
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "source": "opensky",
        "dataset": "aircraft_italy",
        "generated_at": generated_at,
        "opensky_time": raw.get("time"),
        "count": len(features),
        "features": features,
    }


def collect_satellite_tle(generated_at: str) -> dict[str, Any]:
    """Collect selected active satellite GP/TLE lines from CelesTrak."""

    url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"

    try:
        text = request_text(url)
    except requests.RequestException as exc:
        return {
            "source": "celestrak",
            "dataset": "satellites_active_tle",
            "generated_at": generated_at,
            "count": 0,
            "error": exc.__class__.__name__,
            "satellites": [],
        }

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    satellites: list[dict[str, Any]] = []

    for index in range(0, len(lines) - 2, 3):
        name, line1, line2 = lines[index], lines[index + 1], lines[index + 2]
        if not line1.startswith("1 ") or not line2.startswith("2 "):
            continue

        satellites.append(
            {
                "name": name,
                "norad_id": line1[2:7].strip(),
                "tle_line_1": line1,
                "tle_line_2": line2,
            }
        )

    return {
        "source": "celestrak",
        "dataset": "satellites_active_tle",
        "generated_at": generated_at,
        "count": len(satellites),
        "satellites": satellites,
    }


def parse_feed_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        return value


def text_or_none(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def collect_feed(feed: FeedConfig, generated_at: str) -> dict[str, Any]:
    try:
        xml_text = request_text(feed.url)
        root = ET.fromstring(xml_text)
    except (requests.RequestException, ET.ParseError) as exc:
        return {
            "source": feed.name,
            "dataset": "rss_events",
            "category": feed.category,
            "generated_at": generated_at,
            "count": 0,
            "error": exc.__class__.__name__,
            "items": [],
        }

    items: list[dict[str, Any]] = []

    if root.tag.endswith("feed"):
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            link_element = entry.find("atom:link", ns)
            items.append(
                {
                    "title": text_or_none(entry.find("atom:title", ns)),
                    "link": link_element.attrib.get("href") if link_element is not None else None,
                    "published_at": text_or_none(entry.find("atom:updated", ns)),
                    "summary": text_or_none(entry.find("atom:summary", ns)),
                    "category": feed.category,
                }
            )
    else:
        for item in root.findall(".//item"):
            items.append(
                {
                    "title": text_or_none(item.find("title")),
                    "link": text_or_none(item.find("link")),
                    "published_at": parse_feed_datetime(text_or_none(item.find("pubDate"))),
                    "summary": text_or_none(item.find("description")),
                    "category": feed.category,
                }
            )

    return {
        "source": feed.name,
        "dataset": "rss_events",
        "category": feed.category,
        "generated_at": generated_at,
        "count": len(items),
        "items": items[:100],
    }


def collect_events(generated_at: str) -> dict[str, Any]:
    feeds = [collect_feed(feed, generated_at) for feed in RSS_FEEDS]
    items: list[dict[str, Any]] = []
    for feed_payload in feeds:
        for item in feed_payload.get("items", []):
            item["source"] = feed_payload.get("source")
            items.append(item)

    return {
        "source": "rss_feeds",
        "dataset": "events",
        "generated_at": generated_at,
        "feed_count": len(RSS_FEEDS),
        "count": len(items),
        "feeds": feeds,
        "items": items,
    }


def remove_old_history(now: datetime) -> None:
    if not HISTORY_DIR.exists():
        return

    for child in HISTORY_DIR.iterdir():
        if not child.is_dir():
            continue
        try:
            folder_date = datetime.strptime(child.name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age_days = (now - folder_date).days
        if age_days > RETENTION_DAYS:
            shutil.rmtree(child)


def update_index(generated_at: str, history_files: list[str]) -> None:
    index_path = DATA_DIR / "index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            index = {"snapshots": []}
    else:
        index = {"snapshots": []}

    index["last_update"] = generated_at
    index["latest"] = {
        "aircraft_italy": "data/latest/aircraft_italy.geojson",
        "satellites_active_tle": "data/latest/satellites_active_tle.json",
        "events": "data/latest/events.json",
    }
    index.setdefault("snapshots", [])
    index["snapshots"].append({"generated_at": generated_at, "files": history_files})
    index["snapshots"] = index["snapshots"][-500:]

    write_json(index_path, index)


def main() -> None:
    now = utc_now()
    generated_at = now.isoformat()
    date_part = now.strftime("%Y-%m-%d")
    time_part = now.strftime("%H%M%S")

    aircraft = collect_aircraft_italy(generated_at)
    satellites = collect_satellite_tle(generated_at)
    events = collect_events(generated_at)

    latest_files = {
        LATEST_DIR / "aircraft_italy.geojson": aircraft,
        LATEST_DIR / "satellites_active_tle.json": satellites,
        LATEST_DIR / "events.json": events,
    }

    history_files = {
        HISTORY_DIR / date_part / f"aircraft_italy_{time_part}.geojson": aircraft,
        HISTORY_DIR / date_part / f"satellites_active_tle_{time_part}.json": satellites,
        HISTORY_DIR / date_part / f"events_{time_part}.json": events,
    }

    for path, payload in latest_files.items():
        write_json(path, payload)

    for path, payload in history_files.items():
        write_json(path, payload)

    remove_old_history(now)
    update_index(
        generated_at=generated_at,
        history_files=[str(path.relative_to(REPO_ROOT)) for path in history_files],
    )

    print("OSINT data collection completed")
    print(f"generated_at={generated_at}")
    print(f"aircraft_count={aircraft.get('count')}")
    print(f"satellite_tle_count={satellites.get('count')}")
    print(f"event_count={events.get('count')}")


if __name__ == "__main__":
    main()
