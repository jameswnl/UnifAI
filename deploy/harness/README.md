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
# Base: MAS API + MongoDB, in-process engine — 2 containers
podman compose -f deploy/harness/compose.yaml up --build

# Smoke test
curl http://localhost:8002/api/health

# Optional scale-out pieces
podman compose -f deploy/harness/compose.yaml --profile streaming up   # + Redis
ENGINE_NAME=temporal podman compose -f deploy/harness/compose.yaml --profile temporal up  # + Temporal & worker
```

## Harness profile (Kubernetes / OpenShift)

The helm layout is already per-service; the harness profile is just the
multiagent helmfile alone:

```bash
helmfile -f helm/multiagent.yaml.gotmpl apply
```

## Platform profile (everything)

Apply each service helmfile (`helm/*.yaml.gotmpl`) — see [helm/README.md](../../helm/README.md).
