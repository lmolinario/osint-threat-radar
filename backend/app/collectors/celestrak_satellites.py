from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests


DEFAULT_GROUP = "stations"
CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"

HEADERS = {
    "User-Agent": "OSINT-Threat-Radar/0.1 (+https://www.dfaas.it)",
}

# Starlink and other very large constellations are more robust through OMM JSON
# because legacy fixed-width TLEs are increasingly fragile for new catalog IDs.
JSON_FIRST_GROUPS = {"starlink"}


def fetch_celestrak_tle(group: str = DEFAULT_GROUP, timeout: int = 20) -> str:
    params = {"GROUP": group.upper(), "FORMAT": "TLE"}
    response = requests.get(CELESTRAK_GP_URL, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_celestrak_json(group: str = DEFAULT_GROUP, timeout: int = 30) -> List[Dict[str, Any]]:
    params = {"GROUP": group.upper(), "FORMAT": "JSON"}
    response = requests.get(CELESTRAK_GP_URL, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        return []
    return data


def parse_tle_triplets(tle_text: str) -> List[Dict[str, Any]]:
    """
    Parse CelesTrak TLE/3LE records into normalized catalog items.
    """
    lines = [line.strip() for line in tle_text.splitlines() if line.strip()]
    out: List[Dict[str, Any]] = []
    i = 0

    while i + 2 < len(lines):
        name = lines[i]
        line1 = lines[i + 1]
        line2 = lines[i + 2]

        if line1.startswith("1 ") and line2.startswith("2 "):
            out.append(
                {
                    "name": name,
                    "line1": line1,
                    "line2": line2,
                    "source_format": "tle",
                }
            )
            i += 3
        else:
            i += 1

    return out


def parse_omm_json(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize CelesTrak OMM JSON records for sgp4.omm.initialize().
    """
    out: List[Dict[str, Any]] = []

    for record in records:
        if not isinstance(record, dict):
            continue

        name = record.get("OBJECT_NAME") or record.get("OBJECT_ID") or record.get("NORAD_CAT_ID")
        if not name:
            continue

        # sgp4.omm.initialize expects OMM field values. Converting to strings
        # keeps behavior stable across JSON numeric/string representations.
        omm = {key: "" if value is None else str(value) for key, value in record.items()}

        out.append(
            {
                "name": str(name),
                "norad_id": record.get("NORAD_CAT_ID"),
                "omm": omm,
                "source_format": "omm_json",
            }
        )

    return out


def fetch_celestrak_catalog(group: str = DEFAULT_GROUP) -> List[Dict[str, Any]]:
    group_key = group.lower()

    if group_key in JSON_FIRST_GROUPS:
        records = parse_omm_json(fetch_celestrak_json(group=group))
        if records:
            return records

    tle_records = parse_tle_triplets(fetch_celestrak_tle(group=group))
    if tle_records:
        return tle_records

    # Fallback for groups where TLE is empty, malformed or no longer suitable.
    return parse_omm_json(fetch_celestrak_json(group=group))


class TLECache:
    def __init__(self, ttl_seconds: int = 900):
        self.ttl = ttl_seconds
        self._data: Optional[List[Dict[str, Any]]] = None
        self._ts: float = 0.0
        self._group: str = DEFAULT_GROUP

    def get(self, group: str = DEFAULT_GROUP) -> List[Dict[str, Any]]:
        now = time.time()
        if self._data is not None and (now - self._ts) < self.ttl and group == self._group:
            return self._data

        self._data = fetch_celestrak_catalog(group=group)
        self._ts = now
        self._group = group
        return self._data
