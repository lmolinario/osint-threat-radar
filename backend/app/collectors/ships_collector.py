from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx


BBox = Tuple[float, float, float, float]


DEMO_SHIPS: List[Dict[str, Any]] = [
    {
        "id": "demo-ship-001",
        "name": "TYRRHENIAN MERCHANT",
        "mmsi": "247000001",
        "ship_type": "Cargo",
        "lat": 40.83,
        "lon": 8.23,
        "speed_kn": 14.2,
        "course_deg": 118.0,
        "destination": "Cagliari",
    },
    {
        "id": "demo-ship-002",
        "name": "SARDINIA FERRY",
        "mmsi": "247000002",
        "ship_type": "Passenger",
        "lat": 41.21,
        "lon": 9.18,
        "speed_kn": 18.4,
        "course_deg": 251.0,
        "destination": "Olbia",
    },
    {
        "id": "demo-ship-003",
        "name": "MED PATROL 1",
        "mmsi": "247000003",
        "ship_type": "Patrol",
        "lat": 37.92,
        "lon": 12.52,
        "speed_kn": 9.7,
        "course_deg": 42.0,
        "destination": "Trapani",
    },
    {
        "id": "demo-ship-004",
        "name": "IONIAN TANKER",
        "mmsi": "247000004",
        "ship_type": "Tanker",
        "lat": 38.21,
        "lon": 16.84,
        "speed_kn": 12.9,
        "course_deg": 318.0,
        "destination": "Taranto",
    },
    {
        "id": "demo-ship-005",
        "name": "ADRIATIC CARRIER",
        "mmsi": "247000005",
        "ship_type": "Container",
        "lat": 44.28,
        "lon": 13.56,
        "speed_kn": 16.1,
        "course_deg": 339.0,
        "destination": "Trieste",
    },
    {
        "id": "demo-ship-006",
        "name": "LIGURIAN RO-RO",
        "mmsi": "247000006",
        "ship_type": "Ro-Ro",
        "lat": 43.62,
        "lon": 8.91,
        "speed_kn": 13.4,
        "course_deg": 87.0,
        "destination": "Genova",
    },
    {
        "id": "demo-ship-007",
        "name": "AEGEAN SUPPLY",
        "mmsi": "247000007",
        "ship_type": "Offshore Supply",
        "lat": 39.09,
        "lon": 21.21,
        "speed_kn": 10.6,
        "course_deg": 165.0,
        "destination": "Piraeus",
    },
    {
        "id": "demo-ship-008",
        "name": "SUEZ APPROACH",
        "mmsi": "247000008",
        "ship_type": "Bulk Carrier",
        "lat": 31.11,
        "lon": 32.31,
        "speed_kn": 8.9,
        "course_deg": 6.0,
        "destination": "Suez",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inside_bbox(lat: float, lon: float, bbox: Optional[BBox]) -> bool:
    if bbox is None:
        return True
    lamin, lamax, lomin, lomax = bbox
    return lamin <= lat <= lamax and lomin <= lon <= lomax


def _ship_to_feature(ship: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    try:
        lat = float(ship["lat"])
        lon = float(ship["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    ship_id = str(ship.get("id") or ship.get("mmsi") or ship.get("name") or f"{lat},{lon}")

    return {
        "type": "Feature",
        "id": ship_id,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "source": source,
            "name": ship.get("name") or ship_id,
            "mmsi": ship.get("mmsi"),
            "ship_type": ship.get("ship_type") or ship.get("type"),
            "speed_kn": ship.get("speed_kn"),
            "course_deg": ship.get("course_deg"),
            "destination": ship.get("destination"),
            "last_seen": ship.get("last_seen") or _now_iso(),
        },
    }


def _normalize_external_geojson(data: Dict[str, Any], bbox: Optional[BBox]) -> List[Dict[str, Any]]:
    features: List[Dict[str, Any]] = []
    for feature in data.get("features") or []:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if geometry.get("type") != "Point" or len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        if not _inside_bbox(lat_f, lon_f, bbox):
            continue
        properties = feature.get("properties") or {}
        normalized = _ship_to_feature(
            {
                "id": feature.get("id") or properties.get("id") or properties.get("mmsi"),
                "name": properties.get("name") or properties.get("vessel_name") or properties.get("shipname"),
                "mmsi": properties.get("mmsi") or properties.get("MMSI"),
                "ship_type": properties.get("ship_type") or properties.get("type"),
                "lat": lat_f,
                "lon": lon_f,
                "speed_kn": properties.get("speed_kn") or properties.get("sog"),
                "course_deg": properties.get("course_deg") or properties.get("cog"),
                "destination": properties.get("destination"),
                "last_seen": properties.get("last_seen") or properties.get("timestamp"),
            },
            source="ais_external_geojson",
        )
        if normalized:
            features.append(normalized)
    return features


def fetch_ships(bbox: Optional[BBox] = None, demo: bool = True) -> Dict[str, Any]:
    """
    Return ships as a GeoJSON FeatureCollection.

    Production mode can be enabled by setting AIS_GEOJSON_URL to a provider
    endpoint returning a GeoJSON FeatureCollection. Without a configured AIS
    provider, demo=True returns clearly labelled AIS-like demo vessels so the
    frontend layer can be tested locally without API keys.
    """
    provider_url = os.getenv("AIS_GEOJSON_URL")

    if provider_url:
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                response = client.get(provider_url)
                response.raise_for_status()
                data = response.json()
            features = _normalize_external_geojson(data, bbox)
            return {
                "type": "FeatureCollection",
                "generated_at": _now_iso(),
                "source": "ais_external_geojson",
                "count": len(features),
                "error": None,
                "demo": False,
                "features": features,
            }
        except Exception as exc:
            if not demo:
                return {
                    "type": "FeatureCollection",
                    "generated_at": _now_iso(),
                    "source": "ais_external_geojson",
                    "count": 0,
                    "error": f"ais_provider_error_{type(exc).__name__}",
                    "demo": False,
                    "features": [],
                }

    if not demo:
        return {
            "type": "FeatureCollection",
            "generated_at": _now_iso(),
            "source": "ais",
            "count": 0,
            "error": "ais_provider_not_configured",
            "demo": False,
            "features": [],
        }

    features = []
    for ship in DEMO_SHIPS:
        if _inside_bbox(float(ship["lat"]), float(ship["lon"]), bbox):
            feature = _ship_to_feature(ship, source="ais_demo")
            if feature:
                features.append(feature)

    return {
        "type": "FeatureCollection",
        "generated_at": _now_iso(),
        "source": "ais_demo",
        "count": len(features),
        "error": None,
        "demo": True,
        "warning": "Demo AIS-like data. Set AIS_GEOJSON_URL for a real AIS provider.",
        "features": features,
    }
