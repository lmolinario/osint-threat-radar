from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


DEFAULT_GROUP = "stations"
CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"

HEADERS = {
    "User-Agent": "OSINT-Threat-Radar/0.1 (+https://www.dfaas.it)",
}

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "celestrak"
NOT_UPDATED_MARKER = "has not updated since your last successful"


class CelesTrakNotModifiedNoCache(RuntimeError):
    """CelesTrak refused a repeated download and no local cache exists."""


def _cache_path(group: str, fmt: str) -> Path:
    safe_group = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in group.lower())
    return CACHE_DIR / f"{safe_group}.{fmt.lower()}"


def _is_not_updated_response(response: requests.Response) -> bool:
    return response.status_code == 403 and NOT_UPDATED_MARKER in (response.text or "")


def _read_text_cache(path: Path) -> str:
    if not path.exists():
        raise CelesTrakNotModifiedNoCache(f"celestrak_not_modified_no_cache:{path.name}")
    return path.read_text(encoding="utf-8")


def _write_text_cache(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _get_with_text_cache(group: str, fmt: str, timeout: int) -> str:
    params = {"GROUP": group, "FORMAT": fmt.upper()}
    cache_path = _cache_path(group, fmt)

    response = requests.get(CELESTRAK_GP_URL, params=params, headers=HEADERS, timeout=timeout)

    if _is_not_updated_response(response):
        return _read_text_cache(cache_path)

    response.raise_for_status()
    text = response.text
    _write_text_cache(cache_path, text)
    return text


def fetch_celestrak_tle(group: str = DEFAULT_GROUP, timeout: int = 20) -> str:
    return _get_with_text_cache(group=group, fmt="tle", timeout=timeout)


def fetch_celestrak_json(group: str = DEFAULT_GROUP, timeout: int = 30) -> List[Dict[str, Any]]:
    text = _get_with_text_cache(group=group, fmt="json", timeout=timeout)
    data = json.loads(text)
    if not isinstance(data, list):
        return []
    return data


def parse_tle_triplets(tle_text: str, source_format: str = "tle") -> List[Dict[str, Any]]:
    """Parse CelesTrak TLE/3LE records into normalized catalog items."""
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
                    "source_format": source_format,
                }
            )
            i += 3
        else:
            i += 1

    return out


def parse_omm_json(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize CelesTrak OMM JSON records for sgp4.omm.initialize()."""
    out: List[Dict[str, Any]] = []

    for record in records:
        if not isinstance(record, dict):
            continue

        name = record.get("OBJECT_NAME") or record.get("OBJECT_ID") or record.get("NORAD_CAT_ID")
        if not name:
            continue

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
    tle_records = parse_tle_triplets(fetch_celestrak_tle(group=group))
    if tle_records:
        return tle_records

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
