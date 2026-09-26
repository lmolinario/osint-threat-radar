# OSINT Threat Radar

Global OSINT radar platform that aggregates open-source data into lightweight geospatial intelligence snapshots.

Production collection runs on the self-hosted Dell PowerEdge T340. GitHub remains the source-code repository, while runtime data and provider caches are generated locally.

## Current collectors

| Dataset | Source | Output |
|---|---|---|
| Aircraft over Italy | OpenSky public REST API | `data/latest/aircraft_italy.geojson` |
| Active satellite TLE/GP data | CelesTrak | `data/latest/satellites_active_tle.json` |
| Public event feeds | USGS + GDACS RSS/Atom | `data/latest/events.json` |

## Repository data model

```text
.github/workflows/collect-osint-data.yml  # Scheduled GitHub Actions workflow
scripts/collect_osint_data.py             # Python collector
data/latest/                              # Latest dashboard-ready snapshots
data/history/YYYY-MM-DD/                  # Timestamped historical snapshots
data/index.json                           # Snapshot index
```

## Automation

Production automation runs on the Dell PowerEdge T340:

- FastAPI and its internal event schedulers run in Docker;
- the provider cache is checked locally every 5 minutes; CelesTrak external downloads are limited to at least 125 minutes;
- JSON/GeoJSON snapshots are generated locally every 15 minutes;
- GitHub Actions scheduled collectors are disabled;
- GitHub remains the canonical source-code repository;
- the public frontend is served by GitHub Pages.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/collect_osint_data.py
```

## Data retention

The collector keeps historical folders for the last 14 days by default:

```python
RETENTION_DAYS = 14
```

This avoids uncontrolled repository growth while preserving a lightweight OSINT history.

## Notes

This repository is intended as a public MVP/prototype. Git is suitable for small JSON/GeoJSON snapshots, not for high-volume telemetry storage. If data volume grows, the next step should be PostgreSQL/Supabase, object storage, or a dedicated time-series database.
