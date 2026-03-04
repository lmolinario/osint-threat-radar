from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

# Tokenizer (parole intere)
_WORD_RE = re.compile(r"\b([A-Za-zÀ-ÿ'’\-]+)\b", re.IGNORECASE)

# Cache in memoria: key -> (lat, lon) oppure None
_CACHE: Dict[str, Optional[Tuple[float, float]]] = {}

# Dizionario (circa 90 voci): Italia + principali paesi/aree/città
PLACES: Dict[str, Tuple[float, float]] = {
    # --- ITALIA (città/aree) ---
    "italia": (42.8333, 12.8333),
    "roma": (41.9028, 12.4964),
    "milano": (45.4642, 9.1900),
    "napoli": (40.8518, 14.2681),
    "torino": (45.0703, 7.6869),
    "palermo": (38.1157, 13.3615),
    "genova": (44.4056, 8.9463),
    "bologna": (44.4949, 11.3426),
    "firenze": (43.7696, 11.2558),
    "venezia": (45.4408, 12.3155),
    "verona": (45.4384, 10.9916),
    "bari": (41.1171, 16.8719),
    "catania": (37.5079, 15.0830),
    "messina": (38.1938, 15.5540),
    "padova": (45.4064, 11.8768),
    "trieste": (45.6495, 13.7768),
    "taranto": (40.4644, 17.2470),
    "brescia": (45.5416, 10.2118),
    "prato": (43.8777, 11.1023),
    "parma": (44.8015, 10.3279),
    "modena": (44.6471, 10.9252),
    "reggio": (44.6983, 10.6301),  # Reggio Emilia (token "reggio")
    "reggioemilia": (44.6983, 10.6301),
    "reggiocalabria": (38.1112, 15.6470),
    "livorno": (43.5485, 10.3106),
    "cagliari": (39.2238, 9.1217),
    "sassari": (40.7259, 8.5557),
    "olbia": (40.9236, 9.4964),
    "nuoro": (40.3211, 9.3304),
    "oristano": (39.9050, 8.5919),
    "sardegna": (40.1209, 9.0129),
    "sicilia": (37.5999, 14.0154),
    "lombardia": (45.5856, 9.9300),
    "lazio": (41.8928, 12.4837),
    "campania": (40.8390, 14.2525),
    "puglia": (41.1256, 16.8667),
    "toscana": (43.7711, 11.2486),
    "emilia": (44.4949, 11.3426),
    "romagna": (44.0640, 12.5740),
    "piemonte": (45.0522, 7.5154),
    "veneto": (45.4349, 12.3380),
    "liguria": (44.3167, 8.4333),

    # --- EUROPA (paesi/capitale) ---
    "europa": (54.5260, 15.2551),
    "francia": (46.2276, 2.2137),
    "parigi": (48.8566, 2.3522),
    "germania": (51.1657, 10.4515),
    "berlino": (52.5200, 13.4050),
    "spagna": (40.4637, -3.7492),
    "madrid": (40.4168, -3.7038),
    "portogallo": (39.3999, -8.2245),
    "lisbona": (38.7223, -9.1393),
    "regnounito": (55.3781, -3.4360),
    "granbretagna": (55.3781, -3.4360),
    "londra": (51.5074, -0.1278),
    "irlanda": (53.1424, -7.6921),
    "dublino": (53.3498, -6.2603),
    "svizzera": (46.8182, 8.2275),
    "austria": (47.5162, 14.5501),
    "vienna": (48.2082, 16.3738),
    "belgio": (50.5039, 4.4699),
    "bruxelles": (50.8503, 4.3517),
    "olanda": (52.1326, 5.2913),
    "paesibassi": (52.1326, 5.2913),
    "amsterdam": (52.3676, 4.9041),
    "danimarca": (56.2639, 9.5018),
    "norvegia": (60.4720, 8.4689),
    "svezia": (60.1282, 18.6435),
    "finlandia": (61.9241, 25.7482),
    "polonia": (51.9194, 19.1451),
    "varsavia": (52.2297, 21.0122),
    "cechia": (49.8175, 15.4730),
    "praga": (50.0755, 14.4378),
    "slovacchia": (48.6690, 19.6990),
    "ungheria": (47.1625, 19.5033),
    "budapest": (47.4979, 19.0402),
    "romania": (45.9432, 24.9668),
    "bulgaria": (42.7339, 25.4858),
    "grecia": (39.0742, 21.8243),
    "atene": (37.9838, 23.7275),
    "ucraina": (48.3794, 31.1656),
    "kiev": (50.4501, 30.5234),
    "kyiv": (50.4501, 30.5234),
    "russia": (61.5240, 105.3188),
    "mosca": (55.7558, 37.6173),
    "serbia": (44.0165, 21.0059),
    "croazia": (45.1000, 15.2000),
    "slovenia": (46.1512, 14.9955),
    "bosnia": (43.9159, 17.6791),
    "albania": (41.1533, 20.1683),
    "kosovo": (42.6026, 20.9030),

    # --- MEDIO ORIENTE / AFRICA NORD ---
    "medio": (33.0, 44.0),  # fallback per token "medio" (non ideale ma utile)
    "orient e": (33.0, 44.0),  # non verrà matchato normalmente
    "israele": (31.0461, 34.8516),
    "gaza": (31.5017, 34.4668),
    "palestina": (31.9522, 35.2332),
    "iran": (32.4279, 53.6880),
    "iraq": (33.2232, 43.6793),
    "turchia": (38.9637, 35.2433),
    "sir ia": (34.8021, 38.9968),  # non verrà matchato
    "siria": (34.8021, 38.9968),
    "libano": (33.8547, 35.8623),
    "giordania": (30.5852, 36.2384),
    "egitto": (26.8206, 30.8025),
    "libia": (26.3351, 17.2283),
    "tunisia": (33.8869, 9.5375),
    "algeria": (28.0339, 1.6596),
    "marocco": (31.7917, -7.0926),
    "qatar": (25.3548, 51.1839),
    "arabiasaudita": (23.8859, 45.0792),
    "yemen": (15.5527, 48.5164),

    # --- AMERICHE / ASIA (principali) ---
    "usa": (37.0902, -95.7129),
    "statiuniti": (37.0902, -95.7129),
    "washington": (38.9072, -77.0369),
    "newyork": (40.7128, -74.0060),
    "cina": (35.8617, 104.1954),
    "pechino": (39.9042, 116.4074),
    "taiwan": (23.6978, 120.9605),
    "giappone": (36.2048, 138.2529),
    "tokyo": (35.6762, 139.6503),
    "corea": (36.5, 127.8),
    "seul": (37.5665, 126.9780),
    "india": (20.5937, 78.9629),
    "pakistan": (30.3753, 69.3451),
    "afghanistan": (33.9391, 67.7100),
    "brasile": (-14.2350, -51.9253),
    "argentina": (-38.4161, -63.6167),
    "canada": (56.1304, -106.3468),
}

# Normalizzazioni semplici (es. "Regno Unito" -> "regnounito")
ALIASES = {
    "regno": "regnounito",
    "unito": "regnounito",
    "stati": "statiuniti",
    "uniti": "statiuniti",
    "paesi": "paesibassi",
    "bassi": "paesibassi",
    "arabia": "arabiasaudita",
    "saudita": "arabiasaudita",
}


def resolve_latlon(text: str) -> Optional[Tuple[float, float]]:
    """
    Best-effort resolver:
    - tokenizza testo
    - applica alias
    - match su PLACES
    - caching in memoria per la stessa stringa
    """
    if not text:
        return None

    key = text.strip().lower()
    if key in _CACHE:
        return _CACHE[key]

    tokens = [t.lower() for t in _WORD_RE.findall(text)]
    # prova match diretto
    for t in tokens:
        t2 = ALIASES.get(t, t)
        if t2 in PLACES:
            _CACHE[key] = PLACES[t2]
            return _CACHE[key]

    # prova match su bigrammi concatenati (es. "new york" -> "newyork")
    for i in range(len(tokens) - 1):
        joined = f"{tokens[i]}{tokens[i+1]}"
        joined = ALIASES.get(joined, joined)
        if joined in PLACES:
            _CACHE[key] = PLACES[joined]
            return _CACHE[key]

    _CACHE[key] = None
    return None