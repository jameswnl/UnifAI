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

## Harness profile (Podman / Docker)

```bash
# Base: MAS API + PostgreSQL, in-process engine — 2 containers
SECRET_KEY=$(openssl rand -hex 32) \
  podman compose -f deploy/harness/compose.yaml up --build

# Smoke test (health, then a full mock workflow)
curl http://localhost:8002/api/health/
python multi-agent/tests/e2e/harness_smoke.py

# Optional scale-out pieces
REDIS_IP=redis podman compose -f deploy/harness/compose.yaml --profile streaming up          # + Redis
ENGINE_NAME=temporal REDIS_IP=redis \
  podman compose -f deploy/harness/compose.yaml --profile temporal up                        # + Temporal & worker
DB_BACKEND=mongo podman compose -f deploy/harness/compose.yaml --profile mongo up            # Mongo instead of Postgres
```

Reusing the host product's PostgreSQL instead of the bundled one: point
`POSTGRES_DSN` at it and drop the `postgres` service — a 1-container install.

## Harness profile (Kubernetes / OpenShift)

The helm layout is already per-service; the harness profile is just the
multiagent helmfile alone:

```bash
helmfile -f helm/multiagent.yaml.gotmpl apply
```

## Platform profile (everything)

Apply each service helmfile (`helm/*.yaml.gotmpl`) — see [helm/README.md](../../helm/README.md).
