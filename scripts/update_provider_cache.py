#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
update_provider_cache.py

Fetches external live-provider data from GitHub Actions and writes a small
static cache that the Render backend can use when direct provider egress fails.

Outputs:
- provider-cache/metadata.json
- provider-cache/aircraft/italy.geojson
- provider-cache/celestrak/stations.tle
- provider-cache/celestrak/gps-ops.tle
- provider-cache/celestrak/starlink.tle
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


USER_AGENT = "OSINT-Threat-Radar-Provider-Cache/0.1 (+https://www.dfaas.it)"
OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"

# (min_lat, max_lat, min_lon, max_lon)
ITALY_BBOX: Tuple[float, float, float, float] = (35.0, 48.0, 6.0, 19.0)
CELESTRAK_GROUPS = ("stations", "gps-ops", "starlink")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def state_to_feature(row: List[Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(row, list) or len(row) < 17:
        return None

    lon = row[5]
    lat = row[6]
    if lat is None or lon is None:
        return None

    icao24 = row[0]
    return {
        "type": "Feature",
        "id": icao24 or stable_id(json.dumps(row, sort_keys=True, default=str)),
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": {
            "icao24": icao24,
            "callsign": (row[1] or "").strip() or None,
            "origin_country": row[2],
            "time_position": row[3],
            "last_contact": row[4],
            "baro_altitude": row[7],
            "on_ground": row[8],
            "velocity": row[9],
            "true_track": row[10],
            "vertical_rate": row[11],
            "geo_altitude": row[13] if len(row) > 13 else None,
            "squawk": row[14] if len(row) > 14 else None,
            "spi": row[15] if len(row) > 15 else None,
            "position_source": row[16] if len(row) > 16 else None,
            "category": row[17] if len(row) > 17 else None,
        },
    }


def fetch_aircraft_italy(timeout: int) -> Dict[str, Any]:
    lamin, lamax, lomin, lomax = ITALY_BBOX
    params = {
        "lamin": lamin,
        "lamax": lamax,
        "lomin": lomin,
        "lomax": lomax,
        "extended": 1,
    }

    response = requests.get(
        OPENSKY_STATES_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    raw = response.json()

    features: List[Dict[str, Any]] = []
    for row in raw.get("states") or []:
        feature = state_to_feature(row)
        if feature is not None:
            features.append(feature)

    return {
        "type": "FeatureCollection",
        "generated_at": utc_now_iso(),
        "opensky_time": raw.get("time"),
        "bbox": {
            "lamin": lamin,
            "lamax": lamax,
            "lomin": lomin,
            "lomax": lomax,
        },
        "count": len(features),
        "error": None,
        "stale": False,
        "source": "github_actions_provider_cache",
        "features": features,
    }


def fetch_celestrak_tle(group: str, timeout: int) -> str:
    response = requests.get(
        CELESTRAK_GP_URL,
        params={"GROUP": group, "FORMAT": "TLE"},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()

    text = response.text.strip() + "\n"
    if not text.startswith("ISS") and "\n1 " not in text:
        raise RuntimeError(f"Unexpected CelesTrak TLE payload for group={group}")
    return text


def update_cache(out_dir: Path, timeout: int) -> Dict[str, Any]:
    ensure_dir(out_dir)
    metadata: Dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "source": "github_actions_provider_cache",
        "providers": {},
    }

    try:
        aircraft = fetch_aircraft_italy(timeout=timeout)
        write_json(out_dir / "aircraft" / "italy.geojson", aircraft)
        metadata["providers"]["opensky_italy"] = {
            "ok": True,
            "count": aircraft.get("count", 0),
            "opensky_time": aircraft.get("opensky_time"),
            "path": "aircraft/italy.geojson",
        }
        print(f"[ok] OpenSky Italy aircraft count={aircraft.get('count', 0)}")
    except Exception as exc:
        metadata["providers"]["opensky_italy"] = {
            "ok": False,
            "error": type(exc).__name__,
            "path": "aircraft/italy.geojson",
        }
        print(f"[error] OpenSky Italy: {type(exc).__name__}: {exc}", file=sys.stderr)

    for group in CELESTRAK_GROUPS:
        try:
            tle_text = fetch_celestrak_tle(group=group, timeout=timeout)
            line_count = len([line for line in tle_text.splitlines() if line.strip()])
            object_count = line_count // 3
            write_text(out_dir / "celestrak" / f"{group}.tle", tle_text)
            metadata["providers"][f"celestrak_{group}"] = {
                "ok": True,
                "line_count": line_count,
                "estimated_objects": object_count,
                "path": f"celestrak/{group}.tle",
            }
            print(f"[ok] CelesTrak group={group} estimated_objects={object_count}")
        except Exception as exc:
            metadata["providers"][f"celestrak_{group}"] = {
                "ok": False,
                "error": type(exc).__name__,
                "path": f"celestrak/{group}.tle",
            }
            print(f"[error] CelesTrak group={group}: {type(exc).__name__}: {exc}", file=sys.stderr)

    write_json(out_dir / "metadata.json", metadata)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Update static provider cache for OSINT Threat Radar.")
    parser.add_argument("--out", type=Path, default=Path("provider-cache"), help="Output cache directory.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds for provider calls.")
    args = parser.parse_args()

    metadata = update_cache(out_dir=args.out, timeout=args.timeout)

    ok_count = sum(1 for provider in metadata["providers"].values() if provider.get("ok"))
    if ok_count == 0:
        print("[fatal] No provider cache was refreshed successfully.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
