# Deployment Profiles

Two ways to deploy this repo (plan item [0.1], issue #1 — see
[docs/lightspeed-harness/](../../docs/lightspeed-harness/)):

| Profile | What runs | Target |
|---|---|---|
| **harness** | MAS + database only (this directory) | Embedded next to a host product; on-prem installs |
| **platform** | Everything: MAS, UI, RAG, backend, identity | Hosted environment for internal teams (authoring, dashboards) |

Nothing is deleted from the repo — the harness profile is a *subset you deploy*,
so the full platform stays available for hosted use. ("Author hosted, run
embedded.")

## Quick install (Podman / Docker) — recommended

The installer script generates a `SECRET_KEY`, brings up the stack, waits for
health, and can run the smoke test. Base profile is **MAS + PostgreSQL, the
in-process engine — 2 containers** (the default engine is `langgraph`; no
Temporal required).

```bash
./deploy/harness/install.sh up       # generate .env + SECRET_KEY, build, start, health-check
./deploy/harness/install.sh smoke    # full mock workflow end-to-end
./deploy/harness/install.sh down     # stop
```

Configure by editing `deploy/harness/.env` (created from
[`.env.example`](.env.example) on first run) — durability, auth,
notifications, triggers, OTel.

## Manual (compose)

```bash
SECRET_KEY=$(openssl rand -hex 32) \
  podman compose -f deploy/harness/compose.yaml up --build

curl http://localhost:8002/api/health/
python multi-agent/tests/e2e/harness_smoke.py

# Optional scale-out pieces
REDIS_IP=redis podman compose -f deploy/harness/compose.yaml --profile streaming up          # + Redis
ENGINE_NAME=temporal REDIS_IP=redis \
  podman compose -f deploy/harness/compose.yaml --profile temporal up                        # + Temporal & worker
DB_BACKEND=mongo podman compose -f deploy/harness/compose.yaml --profile mongo up            # Mongo instead of Postgres
```

**1-container install:** to reuse the host product's PostgreSQL, point
`POSTGRES_DSN` at it and drop the `postgres` service — MAS alone.

## Harness profile (Kubernetes / OpenShift)

The helm layout is already per-service; the harness profile is just the
multiagent helmfile alone:

```bash
helmfile -f helm/multiagent.yaml.gotmpl apply
```

## Platform profile (everything)

Apply each service helmfile (`helm/*.yaml.gotmpl`) — see [helm/README.md](../../helm/README.md).
