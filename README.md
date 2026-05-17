# OSINT Threat Radar

Global OSINT radar platform that aggregates open-source data into lightweight geospatial intelligence snapshots.

The repository currently includes an automated GitHub Actions collector that periodically gathers public data and stores it under `data/` as JSON/GeoJSON files.

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

The workflow runs every 15 minutes using GitHub Actions cron:

```yaml
- cron: "7/15 * * * *"
```

It can also be started manually from the **Actions** tab using `workflow_dispatch`.

Each run:

1. checks out the repository;
2. installs Python dependencies;
3. runs `scripts/collect_osint_data.py`;
4. updates `data/latest/` and `data/history/`;
5. commits only when data changed.

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
