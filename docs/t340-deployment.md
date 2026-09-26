# T340 production deployment

OSINT Threat Radar production architecture:

GitHub Pages
    |
    | HTTPS
    v
Tailscale Funnel
    |
    v
127.0.0.1:8001
Nginx public gateway
    |
    v
FastAPI :8000
    |
    +-- RSS / Earth Intelligence / Military OSINT
    +-- OpenSky
    +-- CelesTrak
    +-- Local provider cache

## Host

- Dell PowerEdge T340
- Ubuntu-Services
- Docker
- Application directory: /opt/docker/osint-threat-radar

## Public frontend

https://lmolinario.github.io/tools/osint-threat-radar/radar/

## Public API

https://osint-radar.tail8a2be3.ts.net

The API is exposed through Tailscale Funnel and a restricted Nginx gateway.

Only the public GET endpoints required by the frontend are exposed.

Administrative refresh endpoints are not publicly accessible.

## Local services

- FastAPI: 127.0.0.1:8000
- Nginx gateway: 127.0.0.1:8001

## Runtime collectors

Provider cache:
- local T340 container
- refresh interval: 5 minutes
- data directory: runtime/provider-cache

Snapshot collector:
- local T340 container
- refresh interval: 15 minutes
- data directory: runtime/snapshots/data

## GitHub

GitHub remains the canonical source repository.

Scheduled production data collection is executed on the T340 rather than GitHub Actions.

## Backup

The deployment resides under /opt/docker and is included in the existing server backup strategy.
