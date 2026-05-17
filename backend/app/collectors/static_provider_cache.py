from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


DEFAULT_CACHE_BASE_URL = (
    "https://raw.githubusercontent.com/"
    "lmolinario/osint-threat-radar/provider-cache"
)

CACHE_BASE_URL = os.getenv("PROVIDER_CACHE_BASE_URL", DEFAULT_CACHE_BASE_URL).rstrip("/")
CACHE_TIMEOUT = int(os.getenv("PROVIDER_CACHE_TIMEOUT", "6"))

HEADERS = {
    "User-Agent": "OSINT-Threat-Radar-Render-Fallback/0.1 (+https://www.dfaas.it)",
}


def _get_text(path: str) -> Optional[str]:
    url = f"{CACHE_BASE_URL}/{path.lstrip('/')}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=CACHE_TIMEOUT)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
    except Exception as exc:
        print(f"[provider-cache] text fetch error={type(exc).__name__} path={path}")
        return None


def _get_json(path: str) -> Optional[Dict[str, Any]]:
    text = _get_text(path)
    if not text:
        return None
    try:
        data = requests.models.complexjson.loads(text)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        print(f"[provider-cache] json parse error={type(exc).__name__} path={path}")
    return None


def fetch_cached_aircraft_italy() -> Optional[Dict[str, Any]]:
    data = _get_json("aircraft/italy.geojson")
    if not data:
        return None

    data = dict(data)
    data["fallback"] = True
    data["fallback_source"] = "github_actions_provider_cache"
    data["error"] = "opensky_live_unavailable_using_github_actions_cache"
    data["stale"] = True
    return data


def fetch_cached_celestrak_tle(group: str) -> Optional[str]:
    return _get_text(f"celestrak/{group}.tle")
