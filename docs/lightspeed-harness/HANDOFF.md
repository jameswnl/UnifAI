# Handoff — Lightspeed Agent Harness (from UnifAI)

**Purpose of this file:** everything a new agent/engineer needs to continue this
work without the prior conversation. Read this first, then the two companion
docs in this directory.

**Last updated:** 2026-07-20

---

## 1. Mission

Strip the full **UnifAI** multi-agent platform down to a **minimal, embeddable
"Lightspeed Agent Harness"** — a lightweight component a Red Hat product (RHDH,
AAP, OLS, …) can ship next to itself and install on-prem, with a 1–2 container
footprint. It runs product-team-authored agentic workflows with human approval,
durability, escalation, triggers, and observability.

Two source requirement docs drove this (both distilled into the companion docs):
1. `Key-Requirements_Lightspeed-Agent-Harness.md` (discovery requirements)
2. `lightspeed-cloud-agents/docs/architecture-visualization.html` — Goals G1–G5,
   Requirements R1–R12 (a sibling PoC, LCORE-2602).

**Guiding decisions already made (do not re-litigate):**
- **Profiles, not deletion.** Nothing is removed from the repo. The "harness" is
  a *deployment subset* (`PLATFORM_ENDPOINTS=false`, gated modules). The full
  "platform" (UI/RAG/backend/identity) stays deployable for hosted use.
  Mantra: **"author hosted, run embedded."**
- **PostgreSQL over MongoDB** for the harness — host products already run
  Postgres; MongoDB's SSPL license blocks shipping it. Postgres adapters were
  added *beside* Mongo behind existing ports (config-selected via `DB_BACKEND`).
- **Temporal is optional, not required.** The in-process (LangGraph) engine is
  the default and is made durable with a Postgres checkpointer. Temporal is the
  scale-out/OpenShift profile (`ENGINE_NAME=temporal`).
- **The PoC (`lightspeed-cloud-agents`) is a complementary layer, not a
  competitor.** It's production-shaped (see spike). Plan: MAS consumes it as a
  library for the sandbox layer (Phase 3 / M3).

## 2. Companion docs (read these next)

All in `docs/lightspeed-harness/`:
- **`stripdown-analysis.md`** — the full rationale: requirements mapping,
  what to keep/drop, engine architecture, durability gap analysis, escalation
  design. The "why" behind everything.
- **`implementation-plan.md`** — phased, prioritized plan with a **Status**
  section at the top. Build items map to GitHub issues.
- **`poc-maturity-spike.md`** — per-item **import-vs-build verdict** for the
  `lightspeed-cloud-agents` PoC. Essential before starting M3.

## 3. Repo topology

- **Fork:** `github.com/jameswnl/UnifAI` (forked from
  `redhat-community-ai-tools/UnifAI`).
- **Default branch / integration branch:** **`lcs-main`** (not `main`). All PRs
  target `lcs-main`.
- **Local checkout:** `/Users/jwong/ws/UnifAI`. Remotes: `fork` →
  jameswnl/UnifAI (HTTPS, gh credential helper), `origin` → upstream (for
  syncing upstream changes deliberately).
- **`gh` default repo** is set to `jameswnl/UnifAI`, so `gh pr`/`gh issue`
  operate on the fork.
- Issues + milestones (M0–M4) live on the fork. Build items in the plan use
  `[x.y]` numbers that map 1:1 to issue titles.

> **Git gotchas hit before (avoid):** the checkout may show "dubious ownership"
> (run `git config --global --add safe.directory /Users/jwong/ws/UnifAI`); git
> user identity is set repo-locally; a stale root-owned `.git/FETCH_HEAD` can
> block `git pull` (`rm -f .git/FETCH_HEAD` then pull). **Twice a commit
> almost landed on `lcs-main` directly** — always `git checkout -b lcs/<name>
> lcs-main` first. Consider enabling branch protection on `lcs-main`.

## 4. Status

**Complete: milestones M0, M1, M2, M4** (all P0 work + product-integration
surface). 22 PRs merged (#29–#50). Suite: **508 unit tests + integration/E2E**,
all green.

| Milestone | Issues (all closed) | PRs |
|---|---|---|
| M0 baseline | #1 #2 #4 #6 (+#5 spike) | 29,30,31,32,33 |
| M1 Postgres foundation | #7 #8 #9 #10 | 34,35,36,37 |
| M2 durability/retry/escalation | #11 #13 #14 #15 #16 #17 #12 | 38,39,40,41,42,43,44 |
| M4 integration surface | #23 #24 #25 #26 #27 | 45,46,47,48,49 |

**Open issues (remaining work):**
- **M3 — Ephemeral sandbox execution: #18 #19 #20 #21 #22** (see §8).
- **#3** — quarantine burn-down (see §6).
- **#28** — deferred backlog (P2): escalation v2 park-and-resume,
  agents-as-tools registry, cross-workflow memory.

## 5. Architecture established (the seams to build along)

MAS is hexagonal: domain in `multi-agent/lib/mas/`, adapters in
`multi-agent/adapters/`, wiring in `multi-agent/bootstrap/container.py`.
Everything added follows the same pattern — **a port in `lib/mas/`, a
Postgres + Mongo adapter, config-gated construction in the container, a thin
facade that no-ops when disabled.** Established cross-cutting seams:

- **Persistence** — `DB_BACKEND` selects mongo|postgres; repos behind ABC
  ports (`adapters/outbound/{postgres,mongo}/`). New stores follow the
  `PgCollection` JSONB-one-table-per-collection pattern (`postgres/db.py`).
- **Engine** — `BackgroundSessionEngine`/`BaseGraphBuilder` ports; `langgraph`
  (default, checkpointed) and `temporal` adapters. Node execution is the same
  above the seam; only "how the graph is walked" differs.
- **IEM event stream** — every session event flows through one middleware
  choke point. Transcript (#8), audit (#9), and OTel (#25) all ride it.
- **Lifecycle** — `SessionLifecycle` (begin/complete/fail/escalate/cancel) is
  where audit, notifier, and telemetry are emitted. The one place every run
  passes through.
- **HITL** — `ChannelApprovalGate` + `ApprovalGateFactory`; approvals emit
  audit + notifier + a durable `PendingApprovalStore` record.
- **Feature-gating** — `PLATFORM_ENDPOINTS` gates the platform-only endpoint
  groups and their repo construction; `NodeSpec` imports optional node configs
  under try/except so a missing extra degrades to a validation error, not an
  ImportError.

## 6. CI lane + quarantine

Workflow: `.github/workflows/lcs-harness-ci.yml`. **5 jobs gate every PR into
`lcs-main`:**
1. `mas-unit-tests` — full unit suite minus quarantine.
2. `harness-minimal-install` — no a2a/claude/temporal; proves graceful
   degradation + endpoint gating.
3. `harness-e2e` — Mongo service container, headless mock workflow.
4. `harness-e2e-postgres` — Postgres service; runs contract tests + the full
   E2E with checkpointing, resume, and **auth enabled** (asserts 401 without a
   token). This is the most complete gate.
5. `temporal-replay` — in-process time-skipping Temporal test server; workflow
   replay-determinism + claim-check E2E.

**Quarantine:** `multi-agent/tests/quarantine-lcs.txt` is a pytest args-file of
`--deselect` lines for **63 tests already broken on upstream `main`** (tracked
by #3). Unit runs use `pytest tests/unit @tests/quarantine-lcs.txt`. Args-files
don't allow comments — context lives in the workflow header. **#3 is the
burn-down: fix quarantined tests, remove their deselect lines.**

The E2E smoke test is `multi-agent/tests/e2e/harness_smoke.py` (stdlib-only,
`--url`). It does save-blueprint → create → execute → transcript → audit →
webhook-trigger, and presents a bearer token when `HARNESS_AUTH_BEARER_TOKEN`
is set. It's the best "is the harness alive" check.

## 7. Local dev environment

The scratchpad venv from the prior session is **session-specific and gone** —
recreate one. Postgres/Mongo run as local podman containers.

```bash
# 1. Python env (from repo root)
python3 -m venv /tmp/mas-venv
/tmp/mas-venv/bin/pip install -e "./global_utils[multi-agent]"
/tmp/mas-venv/bin/pip install -e "./multi-agent[flask,mongo,postgres,langgraph,llms,tools,redis,rag,temporal,triggers,otel,test]"

# 2. Databases (podman machine must be running: `podman machine init --now`)
podman run -d --name pg -p 5432:5432 \
  -e POSTGRES_USER=unifai -e POSTGRES_PASSWORD=unifai -e POSTGRES_DB=unifai docker.io/library/postgres:16
# (mongo only if testing the mongo backend)
podman run -d --name mongo -p 27017:27017 docker.io/library/mongo:8

# 3. Unit tests (from multi-agent/)
cd multi-agent
/tmp/mas-venv/bin/python -m pytest tests/unit -q @tests/quarantine-lcs.txt

# 4. Postgres contract + integration tests
POSTGRES_DSN=postgresql://unifai:unifai@localhost:5432/unifai \
  /tmp/mas-venv/bin/python -m pytest tests/integration/postgres tests/integration/temporal -q

# 5. Run the API (harness profile) + smoke test
env REDIS_IP= ENGINE_NAME=langgraph PLATFORM_ENDPOINTS=false DB_BACKEND=postgres \
  POSTGRES_DSN=postgresql://unifai:unifai@localhost:5432/unifai SECRET_KEY=dev \
  /tmp/mas-venv/bin/mas api dev --port 8002 &
/tmp/mas-venv/bin/python tests/e2e/harness_smoke.py --url http://localhost:8002
```

Or just: **`./deploy/harness/install.sh up && ./deploy/harness/install.sh smoke`**
(builds and runs the whole stack via compose).

> **Config gotchas hit before:** `get_redis_url()` builds a URL from the
> `redis_ip` *default* (`localhost`), so leaving it unset makes the app pick
> the Redis channel factory and fail with no Redis running — **set
> `REDIS_IP=""` explicitly** for the light profile. The container still imports
> Mongo classes at module level, so the `mongo` extra (client lib) must be
> installed even on the postgres backend (cleanup is a known follow-up).

## 8. Next work — M3 (ephemeral sandbox execution)

**Goal (doc 2 R4/R7/R8):** each agent step runs in a fresh ephemeral sandbox
container spawned via a platform abstraction. This lands *below* the engine
seam — it's a new node type + a spawner adapter; the Temporal/LangGraph engines
are untouched (see analysis §7). Per the spike, **most of it is importable**
from `lightspeed-cloud-agents/src/cloud_agents/` (asyncio/FastAPI; use the
existing `AsyncBridge` when wiring into MAS's sync paths).

Suggested order:
- **#18 Spawner port + Podman impl** — port with `spawn/await/destroy/reconcile`;
  Podman first (proves the installer profile), then K8s. Import from PoC
  `spawner/` (has K8s 558 LOC, Podman 335, OpenShell 1092). Content-hash pod
  naming → idempotent retries (pairs with the retry loop #11 + resume #13).
  *Unit-testable now with a mock spawner; real spawn needs Podman/K8s.*
- **#19 Sandbox runtime image** — adopt the PoC's published
  `quay.io/openshift-lightspeed/lightspeed-agentic-sandbox` (contract:
  `POST /v1/agent/run` with query + outputSchema). Don't build from scratch.
  *This is the blocker for a true end-to-end M3 test — you need the image.*
- **#20 `sandbox_agent_node`** — new catalog element (auto-discovered via
  `spec/__init__.py`, see how mock_agent/branch_chooser were re-enabled):
  spawn → POST /v1/agent/run → collect structured output → destroy. Per-node
  choice; deterministic nodes stay in-process.
- **#21 Sandbox security** — runner↔sandbox TLS, network-level credential
  injection, per-step tool allow/deny. Heavily importable (PoC `tls.py`,
  `content_policy.py`, egress tests).
- **#22 In-sandbox events → IEM stream** — so live streaming + transcript work
  for sandboxed steps (forward the sandbox's events into the persisting
  channel).

**Why it was paused here:** M3 needs the published sandbox image + real
container infra to verify end-to-end, and cleanly importing cross-repo
asyncio/FastAPI code into MAS's structure is a distinct chunk of work best
started deliberately. Everything through M4 is verifiable in CI without that.

## 9. Conventions

- **One issue → one branch (`lcs/<slug>` off `lcs-main`) → one squash-merged
  PR.** Delete the branch on merge (`--delete-branch`).
- **Always add tests** and keep all 5 CI jobs green before merging. New DB code
  gets a `tests/integration/postgres` contract test (DSN-gated skip). New
  cross-cutting behavior gets an E2E step.
- **Best-effort by default:** transcript/audit/notifier/telemetry failures log,
  never break a run. New facades follow this and expose a `NULL_*` no-op.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  PR body trailer: the Claude Code generated-with line.
- Watch CI with `gh pr checks <branch> --watch`; merge with
  `gh pr merge <n> --squash --delete-branch`; then on `lcs-main`
  `rm -f .git/FETCH_HEAD && git pull -q fork lcs-main`.
