import time
from typing import List, Dict, Optional
import requests


DEFAULT_GROUP = "stations"  # per test: pochi satelliti (ISS ecc.)
CELESTRAK_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php"


def fetch_celestrak_tle(group: str = DEFAULT_GROUP, timeout: int = 20) -> str:
    params = {"GROUP": group, "FORMAT": "tle"}
    r = requests.get(CELESTRAK_TLE_URL, params=params, timeout=timeout)
    r.raise_for_status()
    return r.text


def parse_tle_triplets(tle_text: str) -> List[Dict]:
    # formato: NAME \n 1 ... \n 2 ... \n ripetuto
    lines = [ln.strip() for ln in tle_text.splitlines() if ln.strip()]
    out = []
    i = 0
    while i + 2 < len(lines):
        name = lines[i]
        l1 = lines[i + 1]
        l2 = lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            out.append({"name": name, "line1": l1, "line2": l2})
            i += 3
        else:
            i += 1
    return out


class TLECache:
    def __init__(self, ttl_seconds: int = 900):
        self.ttl = ttl_seconds
        self._data: Optional[List[Dict]] = None
        self._ts: float = 0.0
        self._group: str = DEFAULT_GROUP

    def get(self, group: str = DEFAULT_GROUP) -> List[Dict]:
        now = time.time()
        if self._data is not None and (now - self._ts) < self.ttl and group == self._group:
            return self._data

        tle_text = fetch_celestrak_tle(group=group)
        self._data = parse_tle_triplets(tle_text)
        self._ts = now
        self._group = group
        return self._data