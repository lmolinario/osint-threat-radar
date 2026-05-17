from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.collectors.static_provider_cache import fetch_cached_celestrak_tle


DEFAULT_GROUP = "stations"
CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"

HEADERS = {
    "User-Agent": "OSINT-Threat-Radar/0.1 (+https://www.dfaas.it)",
}

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "celestrak"
NOT_UPDATED_MARKER = "has not updated since your last successful"
CELESTRAK_TIMEOUT = int(os.getenv("CELESTRAK_TIMEOUT", "8"))
ERROR_BACKOFF_SECONDS = int(os.getenv("CELESTRAK_ERROR_BACKOFF_SECONDS", "120"))


class CelesTrakNotModifiedNoCache(RuntimeError):
    """CelesTrak refused a repeated download and no local cache exists."""


class CelesTrakTemporarilyUnavailable(RuntimeError):
    """CelesTrak is temporarily unavailable and no usable cache exists."""


def _cache_path(group: str, fmt: str) -> Path:
    safe_group = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in group.lower())
    return CACHE_DIR / f"{safe_group}.{fmt.lower()}"


def _error_path(group: str, fmt: str) -> Path:
    safe_group = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in group.lower())
    return CACHE_DIR / f"{safe_group}.{fmt.lower()}.error.json"


def _is_not_updated_response(response: requests.Response) -> bool:
    return response.status_code == 403 and NOT_UPDATED_MARKER in (response.text or "")


def _read_text_cache(path: Path) -> str:
    if not path.exists():
        raise CelesTrakNotModifiedNoCache(f"celestrak_not_modified_no_cache:{path.name}")
    return path.read_text(encoding="utf-8")


def _write_text_cache(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_error_marker(path: Path, error: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": time.time(), "error": error}), encoding="utf-8")


def _recent_error(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0))
        if time.time() - ts < ERROR_BACKOFF_SECONDS:
            return str(data.get("error") or "recent_provider_error")
    except Exception:
        return None
    return None


def _fallback_tle_from_github_actions(group: str, cache_path: Path) -> Optional[str]:
    text = fetch_cached_celestrak_tle(group)
    if not text:
        return None
    _write_text_cache(cache_path, text)
    print(f"[celestrak] using GitHub Actions provider cache group={group}")
    return text


def _get_with_text_cache(group: str, fmt: str, timeout: int) -> str:
    params = {"GROUP": group, "FORMAT": fmt.upper()}
    cache_path = _cache_path(group, fmt)
    error_path = _error_path(group, fmt)

    recent_error = _recent_error(error_path)
    if recent_error and cache_path.exists():
        print(f"[celestrak] using local cache after recent error group={group} fmt={fmt} error={recent_error}")
        return _read_text_cache(cache_path)
    if recent_error and not cache_path.exists() and fmt.lower() == "tle":
        fallback = _fallback_tle_from_github_actions(group, cache_path)
        if fallback:
            return fallback
    if recent_error and not cache_path.exists():
        raise CelesTrakTemporarilyUnavailable(recent_error)

    try:
        response = requests.get(
            CELESTRAK_GP_URL,
            params=params,
            headers=HEADERS,
            timeout=timeout,
        )

        if _is_not_updated_response(response):
            return _read_text_cache(cache_path)

        response.raise_for_status()
        text = response.text
        _write_text_cache(cache_path, text)
        if error_path.exists():
            error_path.unlink(missing_ok=True)
        return text

    except Exception as exc:
        error_name = type(exc).__name__
        print(f"[celestrak] provider error={error_name} group={group} fmt={fmt}")
        _write_error_marker(error_path, error_name)

        if cache_path.exists():
            return _read_text_cache(cache_path)

        if fmt.lower() == "tle":
            fallback = _fallback_tle_from_github_actions(group, cache_path)
            if fallback:
                return fallback

        raise


def fetch_celestrak_tle(group: str = DEFAULT_GROUP, timeout: int = CELESTRAK_TIMEOUT) -> str:
    return _get_with_text_cache(group=group, fmt="tle", timeout=timeout)


def fetch_celestrak_json(group: str = DEFAULT_GROUP, timeout: int = CELESTRAK_TIMEOUT) -> List[Dict[str, Any]]:
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
                    "source_format": "github_actions_cache_tle" if source_format == "tle" else source_format,
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
        self.error_ttl = ERROR_BACKOFF_SECONDS
        self._data_by_group: Dict[str, List[Dict[str, Any]]] = {}
        self._ts_by_group: Dict[str, float] = {}
        self._error_by_group: Dict[str, Dict[str, Any]] = {}

    def get(self, group: str = DEFAULT_GROUP) -> List[Dict[str, Any]]:
        now = time.time()
        cached = self._data_by_group.get(group)
        cached_ts = self._ts_by_group.get(group, 0.0)

        if cached is not None and (now - cached_ts) < self.ttl:
            return cached

        recent_error = self._error_by_group.get(group)
        if recent_error and (now - float(recent_error.get("ts", 0.0))) < self.error_ttl:
            if cached is not None:
                print(f"[celestrak] serving memory cache group={group} after recent error={recent_error.get('error')}")
                return cached
            # Try GitHub Actions cache through the normal fetch path before failing.

        try:
            data = fetch_celestrak_catalog(group=group)
            self._data_by_group[group] = data
            self._ts_by_group[group] = now
            self._error_by_group.pop(group, None)
            return data
        except Exception as exc:
            error_name = type(exc).__name__
            self._error_by_group[group] = {"ts": now, "error": error_name}
            print(f"[celestrak] cache get error={error_name} group={group}")
            if cached is not None:
                return cached
            raise
