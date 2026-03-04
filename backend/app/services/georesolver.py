import re
from typing import Optional, Tuple

# dizionario minimo (espandibile)
PLACES = {
    "roma": (41.9028, 12.4964),
    "milano": (45.4642, 9.1900),
    "napoli": (40.8518, 14.2681),
    "sassari": (40.7259, 8.5557),
    "cagliari": (39.2238, 9.1217),
    "palermo": (38.1157, 13.3615),
    "torino": (45.0703, 7.6869),
    "bari": (41.1171, 16.8719),
    "iran": (32.4279, 53.6880),        # centro paese
    "iraq": (33.2232, 43.6793),
    "ucraina": (48.3794, 31.1656),
    "israele": (31.0461, 34.8516),
    "gaza": (31.5017, 34.4668),
    "turchia": (38.9637, 35.2433),
    "russia": (61.5240, 105.3188),
}

# match parole intere, case-insensitive
_WORD_RE = re.compile(r"\b([A-Za-zÀ-ÿ'’\-]+)\b", re.IGNORECASE)

def resolve_latlon(text: str) -> Optional[Tuple[float, float]]:
    if not text:
        return None
    tokens = [t.lower() for t in _WORD_RE.findall(text)]
    for t in tokens:
        if t in PLACES:
            return PLACES[t]
    return None