---
name: deploy
description: Deploy podcast-manager to the marcuslab Docker Swarm with deploy.sh (backend, frontend or all), including the alembic migration step and the production hostnames. Use when deploying or when a deploy misbehaves.
---

### Deployment

```bash
[REGISTRY=ghcr.io/marco308] [IMAGE_TAG=<sha>] ./deploy.sh [backend|frontend|all]
```

With `REGISTRY` set it deploys the images CI already published to GHCR, tagged with the checked-out commit — so `git pull` the commit you mean to ship first; `IMAGE_TAG=<sha>` rolls back to an earlier build. Without `REGISTRY` it builds `:latest` locally (single-node only). CI publishes `:latest` and `:<sha>` on every push to `main`, and also after each Dependabot auto-merge (the merge job dispatches CI on `main`).

Migrations run in the container entrypoint (`backend/entrypoint.sh`: `scripts/adopt_legacy_schema.py`, then `alembic upgrade head`) before uvicorn starts — `deploy.sh` does not run them itself. Production hosts: `podcastmanager.marcuslab.uk` (frontend) and `api-podcastmanager.marcuslab.uk` (API).
