# UnifAI Strip-Down Analysis — Minimal Lightspeed Agent Harness

**Date:** 2026-07-20
**Repo analyzed:** `redhat-community-ai-tools/UnifAI` @ `188d389f4` (main)
**Requirement sources:**

1. `Key-Requirements_Lightspeed-Agent-Harness.md` (this directory) — discovery-session requirements
2. `lightspeed-cloud-agents/docs/architecture-visualization.html` — Goals G1–G5, Requirements R1–R12, FAQ (PoC LCORE-2602)

**Implementation plan:** [implementation-plan.md](implementation-plan.md) — phased, prioritized sequencing of the build items below.

**Question:** Can UnifAI — a full AI agent platform — be stripped down to the smallest footprint that satisfies the Lightspeed Agent Harness requirements, deployable as a lightweight ancillary component to existing products (RHDH, AAP, etc.), installable on-prem by customers?

**Answer:** Yes. Cut to the `multi-agent/` (MAS) core + `global_utils`, drop ~80% of the codebase and 4 of 6 infrastructure dependencies, swap MongoDB for PostgreSQL, and add a short list of build items (per-step sandbox spawning, triggers, OTel, durable HITL, transcript/audit persistence). The engine architecture (Temporal/LangGraph behind one port) survives intact and absorbs the ephemeral-sandbox execution model as a new node type — not a rearchitecture.

---

## 1. What UnifAI Is Today

A multi-agent AI workflow platform:

- **`multi-agent/` (MAS)** — orchestration engine. YAML blueprints define agent graphs (nodes, edges, conditions); pluggable element catalog (agent nodes, tools, LLMs, MCP/A2A providers, retrievers, sandboxes); two execution engines (in-process LangGraph, distributed Temporal); NDJSON/Redis-Streams event streaming; HITL approval gates; hexagonal architecture (domain in `lib/mas`, adapters for Flask/Temporal/Mongo/Redis).
- **`rag/`** — ingestion pipeline (Slack, PDF, Markdown → Qdrant vectors, Celery workers, RabbitMQ).
- **`ui/`** (31 MB) — React drag-and-drop blueprint builder + RAG dashboard.
- **`backend/`** — platform service (admin config, Slack commands).
- **`shared-resources/identity/`** — Keycloak OAuth/OIDC identity service.
- **`cli/`** — terminal client for MAS (needs only MAS + DB).
- **Infra:** MongoDB, Qdrant, RabbitMQ, Redis, Temporal, Keycloak.

---

## 2. Requirements Mapping

### 2.1 Doc 1 (Key Requirements) vs UnifAI

| Requirement | UnifAI status |
|---|---|
| Deployable agentic workflows, product-specific actions | ✅ MAS blueprints + element catalog |
| Human approval before system changes | ✅ HITL gates (`core/hitl`, `adapters/outbound/hitl`, `claude_agent` PreToolUse hook) |
| Long-running proactive workflows (scheduled/triggered) | ⚠️ Temporal gives durable execution; **no scheduler/cron/alert-trigger mechanism exists** |
| Sandboxed local tools, skills, remote MCP | ✅ partial — `openshell_sandbox` element, `mcp_proxy` tool, `mcp_server_client` provider, `claude_agent` node (Claude Agent SDK + sandbox tools) |
| Context management (sub-agents, compaction) | ⚠️ partial — `deep_agent`/`orchestrator` delegation; compaction only via Claude SDK node |
| OTel observability | ❌ absent |
| End-users cannot author agents (internal-only authoring) | ❌ **conflict** — the UI builder/sharing/collaboration exist to let users author agents. Strippable on principle, not just size |
| Lightweight; OpenShift + Podman | ❌ heavy infra; Helm/OpenShift only, no Podman path |

### 2.2 Doc 2 (Cloud Agents PoC) — Goals & Requirements

- **G1** BYO agents/workflows (YAML + any tools, no framework changes)
- **G2** Secured & governed execution (ephemeral containers, scoped permissions, approval gates, full observability)
- **G3** Composable ecosystem (agents-as-tools; triggers: conversation, alert, API, schedule)
- **G4** Human follow-up with preserved context (escalation packaging)
- **G5** Kubernetes **and** Podman targets, same workflow model

Key requirements: R1 framework-not-agents · R2 multi-step workflows with conditions/retry/approval, risk levels · R3 human-out-of-the-loop escalation with failure history · **R4 ephemeral-by-default (fresh sandbox container per agent step)** · R5 stateless runner, durable state · R6 full transcript persistence across steps · R7 cross-platform spawner abstraction · R8 security (credential isolation, TLS runner↔sandbox, per-step tool scoping, audit) · R9 pluggable RBAC, fail-closed · R10 OTel/Prometheus/structured logging · R11 API/alert/schedule triggers · R12 agents-as-tools.

**Biggest architectural difference from UnifAI:** doc 2 wants every agent step to run in a fresh ephemeral sandbox container spawned through a platform abstraction (K8s/Podman/OpenShell), with a thin stateless runner. UnifAI executes agent nodes **in-process** inside its workers; sandboxes are only a tool an agent may call. See §7 for why this is absorbable rather than fatal.

**Note (user decision):** Temporal and PostgreSQL in doc 2 are *implementation choices*, not requirements. The actual goals: durable/restartable/auditable workflows + full transcript/history storage. Any infra that achieves these is acceptable.

---

## 3. The Strip-Down Plan

> **Revision (2026-07-20): strip-down = profiles, not deletion.** To preserve the option of deploying the full platform in a hosted environment, nothing below is deleted from the repo. "Drop" means **excluded from the harness deployment profile**; "prune" means **feature-gated off** in that profile. Mechanics:
>
> 1. **Deployment level** — UnifAI is already a multi-service monorepo (`ui`, `rag`, `backend`, `identity`, `multi-agent` are separate deployables). Two profiles: **`harness`** (MAS + Postgres, 1–2 containers) and **`platform`** (everything, incl. Mongo/Qdrant/Keycloak). Helmfile composes per service already; a Podman compose file per profile covers on-prem. Not deploying a service achieves what deleting it would.
> 2. **Code level inside MAS** — prune-list modules become conditional: Flask endpoint groups registered per profile config, catalog elements optional (auto-discovery already tolerates absent extras), deps split via existing pip extras. Harness profile installs `mas[flask,postgres,langgraph,claude,tools]` and never loads platform-only modules.
> 3. **Persistence** — Postgres adapters are **added beside** the Mongo ones behind the existing repository ports (config-selected), rather than replacing them. Licensing is coherent: SSPL constrains *shipping* Mongo to customers, not running it in Red Hat's own hosted env → hosted-full-on-Mongo, shipped-harness-on-Postgres.
> 4. **Requirement-3 conflict resolved, not amputated** — the authoring UI lives on in the hosted platform where *internal* product teams author/test blueprints; the embedded harness profile only executes them. **"Author hosted, run embedded."**
> 5. **Cost / risk** — dual persistence backends and a profile-drift risk (minimal profile regressing while everyone develops against full). Non-negotiable mitigation: CI job building + E2E-testing the harness profile on every PR.

### Drop entirely (~85% of repo weight) — *i.e. excluded from the harness profile*

| Component | Size | Rationale |
|---|---|---|
| `ui/` | 31 MB | End-user authoring violates internal-only-authoring requirement; embedded agents are headless |
| `rag/` | 1.2 MB + Qdrant/RabbitMQ/Celery | Not in either requirement set. Doc 2 delivers domain knowledge as **skills in OCI images**; use-case retrieval (Git/Jira/docs) fits MCP tools |
| `backend/` | 196 KB | UI-serving platform service (admin config, Slack commands) |
| `shared-resources/identity/` | 276 KB | Keycloak platform SSO; replace with thin auth middleware (bearer + K8s TokenReview, pluggable RBAC per R8/R9) |
| `mcp_servers/`, most of `helm/`, `ci/`, most of `local-development/` | — | Follow the dropped components |

### Keep

- **`multi-agent/`** — pruned:
  - **Keep:** `blueprints`, `engine`, `catalog`, `session`, `core` (incl. `hitl`, `iem`), nodes (`custom_agent`, `orchestrator`, `branch_chooser`, `user_question`, `final_answer`, `claude_agent`), `sandboxes`, tools (`mcp_proxy`, `ssh_exec`, `oc_exec`, `web_fetch`), `providers/mcp_server_client`, `conditions`, LLM providers, both engine adapters.
  - **Prune:** `sharing`/`shares`, `collaboration`, `statistics`, `workspace`, `retrievers` (depend on dropped RAG service), `actions/providers/rag`, template UI-support layer. Flask endpoints map 1:1 to these — API surface shrinks accordingly.
- **`global_utils/`** — shared dependency.
- **`cli/`** (104 KB) — with the UI gone, this is how internal teams test blueprints. Needs only MAS + DB.

### What survives under *both* requirement docs (the durable core)

Temporal engine integration · blueprint YAML resolution/validation/storage · conditional routing · HITL gate machinery · NDJSON/Redis event streaming · MCP integration · OpenShell sandbox client. The in-process agent-loop node implementations are the part doc 2's model bypasses (§7).

---

## 4. Storage: MongoDB → PostgreSQL

**Is MongoDB heavy?** Not in resources (~500 MB–1 GB RAM single container). It is wrong for this deployment model:

1. **Licensing.** SSPL is not OSI-approved; Red Hat removed MongoDB from RHEL 8 over it. Shipping it in a supported Red Hat installer faces policy resistance before technical debate.
2. **New stateful service = the real cost.** Every stateful dependency added to a host product needs install/upgrade/backup/HA/support-matrix treatment. Infra cost is operational surface, not megabytes.
3. **Host products already run PostgreSQL.** RHDH (Backstage) requires it; AAP ships and manages it. "Point me at a schema in your existing Postgres" adds **zero** new stateful infra.

**Swap difficulty: contained.** `pymongo` appears in exactly 7 adapter files (`adapters/outbound/mongo/*_repository.py`); domain code depends on abstract ports (`SessionRepository(ABC)` etc.); stored documents are Pydantic models → Postgres JSONB. Only genuinely Mongo-flavored code is the `$facet` analytics aggregations — already on the strip list. ~4 repository ports survive (sessions, blueprints, resources, client config).

**Redis** — stays optional (live streaming, at small scale falls back to DB). **Temporal** — optional, itself Postgres-backed, so even the distributed profile is single-database.

**Floor:** 2 containers (harness + Postgres), or **1** if the host product's Postgres is reused.

---

## 5. Durability, Restartability, Auditability, Transcripts — Gap Analysis

Goals (per user reframing): durable/restartable/auditable workflows; full transcript & history storage. Current UnifAI state:

| Capability | Current state | Gap |
|---|---|---|
| Transcript granularity | ✅ IEM events carry node lifecycle, task results/artifacts, errors; `claude_agent` emits per-tool-call events with call IDs | — |
| Transcript **persistence** | ❌ Events live only in Redis Streams, default TTL 1 h (`channel.py:38`). Nothing writes events to the DB. Mongo stores only final `SessionRecord` (identity, blueprint, status, final `graph_state`) | Durable event sink → `session_events` table, fed from the `core/iem/middleware` choke point. (`REDIS_STREAM_TTL=0` is not an answer — unbounded Redis as system-of-record) |
| Durability — Temporal mode | ✅ Temporal Server owns workflow state | — |
| Durability — LangGraph mode | ❌ **No checkpointing at all**; worker crash strands the session | Postgres-backed LangGraph checkpointer (`langgraph-checkpoint-postgres`, off-the-shelf) + resume-on-startup scan of non-terminal sessions |
| HITL waits | ❌ Redis gate keys hard-coded **300 s TTL** (`channel.py:33`). Days-long approvals impossible in *either* engine mode | Persist pending approvals in DB; see §6 gap 1 for the Temporal-side fix |
| Audit trail | ❌ Absent (closest thing: session status transitions) | Audit middleware on the IEM pipeline → typed `audit_events` records (workflow start/end, approvals, spawns, escalations) |

**Conclusion:** the *database* can meet both goals — and per §4 the database should be Postgres. No new infra category needed; the gaps are plumbing, all landing on the same IEM middleware hook and repository ports.

---

## 6. Engine Architecture: Temporal vs LangGraph

### The seam

Domain code never touches either engine. Abstract port `BackgroundSessionEngine` (`lib/mas/session/execution/ports.py:25`); two adapters (`adapters/outbound/temporal/`, `adapters/outbound/langgraph/`); bootstrap picks one from `engine_name` config (`bootstrap/container.py:393`; current default `"temporal"` — should flip to local for the installer profile). Pip extras split dependencies (`[temporal]` vs `[langgraph]`). Same blueprint YAML runs on either.

**It is either/or per deployment, and the engines are siblings, not layers.** The Temporal adapter has zero LangGraph imports — both implement the same `BaseGraphBuilder`/`BaseGraphExecutor` abstraction. LangGraph is not the "agent framework"; it is one interchangeable implementation of "walk the graph, run nodes, evaluate conditions." Everything above the line (blueprints, catalog, HITL, streaming) is engine-agnostic.

### Why Temporal is optional-not-required

Production Temporal = 4 services + own Postgres schemas + migration tooling + SDK/server version management. For a customer-installed ancillary component that triples the moving parts. A DB-checkpointed single node meets the durability *goal*.

### Why Temporal is optional-not-dropped

Durable timers (a 3-day approval wait costs nothing), automatic retry policies, horizontally scaled workers, battle-tested crash recovery. OpenShift-scale use cases (SRE agent under alert storms, fleet CVE triage) want this; rebuilding it would be the worst outcome.

### Temporal path readiness (code review)

**Implemented end-to-end, right granularity — not a stub:**
- Real worker (`mas temporal-worker`): thread pool, configurable pollers, multi-replica.
- **Per-node activities** — `GraphTraversalWorkflow` executes each node and condition as its own activity ⇒ Temporal history checkpoints at node boundaries. The hard part to retrofit is already done.
- Heartbeats (3 s interval / 10 s timeout), retry policies, workflow queries (state, current nodes), `SessionWorkflow` lifecycle (begin/complete/fail/cancel), Pydantic payload conversion.

**Four gaps to production:**
1. **HITL waits block inside the node activity** — hold a worker thread, must beat the 120-min start-to-close timeout; timeout + retry **re-runs the node**. Fix: lift approvals to workflow **signals + durable timers**. Supersedes the Redis 300 s TTL fix — same root issue.
2. **Full `GraphState` in every activity payload** — Temporal ~2 MB payload cap; accumulating chat/artifacts will hit it. Fix: state-by-reference, bulk content in the Postgres transcript store (pairs with §5).
3. **Blanket 3-attempt retry on side-effectful nodes** (`ssh_exec`/`oc_exec` re-run silently). Fix: per-step retry policy from the workflow definition; default no-retry for high-risk steps (doc 2 R2).
4. **`UnsandboxedWorkflowRunner`** — determinism sandbox disabled. Livable (workflow code is thin) but replay correctness of shared `GraphTraversal` is on us; add a replay test in CI.

### Making the light (LangGraph) mode equivalent

1. Checkpoint after every node (Postgres checkpointer).
2. Resume-on-startup for non-terminal sessions (at-least-once node execution ⇒ steps must be retry-safe; content-hash sandbox naming helps, §7).
3. DB-backed timers/gates (`resume_after`, `awaiting_approval` rows + poller) — folds into the HITL persistence fix.
4. Explicit per-step retry/backoff honored by the LangGraph adapter; Temporal adapter maps the same field to native retry policies.

---

## 7. Ephemeral Sandbox Per Step (Doc 2 R4) — Architectural Impact

**Does it upend the Temporal/LangGraph architecture? No.** It lands below the engine seam, in the node-execution layer both engines share. "Execute node" changes from "run agent loop in-process" to "spawn sandbox → POST `/v1/agent/run` (prompt + output schema) → collect structured output → destroy." Traversal, checkpointing, conditions, the engine port: unchanged.

Per engine:
- **Temporal:** `execute_graph_node` becomes a supervisor activity (spawn/heartbeat/collect/cleanup). *Improves* the fit: activities become I/O-bound; a retried activity spawns a **fresh** sandbox — exactly R4's semantics (content-hash pod naming ⇒ idempotent retries); the payload problem largely dissolves (transcript stays in sandbox/transcript store; activity returns structured output only).
- **LangGraph:** node function spawns instead of executing inline; checkpointer/resume plan unchanged; resume pairs with orphan-container reconciliation.

Also *simplifies*: HITL approval steps spawn no containers (gates live at workflow level — where the signals fix was already headed); fresh-container-per-retry is the contract, not a hazard.

**The real (additive) work:**
1. **Spawner abstraction** — new outbound adapter family (`spawn/await/destroy/reconcile`) with K8s + Podman implementations (R7 verbatim). `openshell_sandbox` client is the closest existing relative; OpenShell can be one implementation.
2. **Sandbox runtime image** — agent loop (LLM, shell, filesystem, skills, MCP) moves into a container with the `/v1/agent/run` contract. Reuse doc 2's `lightspeed-agentic-sandbox` rather than extracting one from UnifAI node code.
3. **New `sandbox_agent_node` element** via the existing (pluggable) catalog. Per-node choice: deterministic nodes (mergers, routers, conditions, final answer) stay in-process; only agent steps pay the spawn cost.
4. **Security/streaming plumbing** — runner↔sandbox ephemeral TLS, network-level secret injection (agent process never sees credentials), in-sandbox events forwarded to the IEM/Redis stream.

**Strategic consequence:** this resolves "which skeleton gets the other's organs" in UnifAI's favor. Its in-process agent-loop nodes get bypassed (the brain relocates to the sandbox image), but its orchestration layer — blueprints, dual engines, catalog, HITL, streaming, persistence — absorbs doc 2's execution model as one new node type plus one new adapter family.

---

## 8. Escalation to Human (R3 / G4) — Design

Running example used throughout this section: the **OLS SRE agent** — an alert fires, the agent diagnoses, proposes a fix, and tries to apply it.

### 8.1 Approval vs escalation — two different things; UnifAI has only one

**Approval** is the human saying *yes before* something happens. The agent reaches "restart the database pod," the workflow pauses and asks "may I?", a human approves, execution continues. UnifAI has this (`ApprovalGate`).

**Escalation** is the opposite direction: the agent *already tried* and couldn't succeed. It restarted the pod, the alert didn't clear; a second remediation failed too. The automation is out of ideas, and the right behavior is: stop, gather everything learned, and hand the case to the on-call engineer — "here's the alert, my diagnosis, the two fixes I attempted, and exactly how each failed."

UnifAI has **no code path for the second thing** (verified — zero escalation code). Its only failure behavior: mark the session `FAILED` in the DB. Nobody is notified, and the detailed record (tool calls, errors) lives in Redis with a 1-hour expiry — by the time a human looks, the evidence is gone.

| Mode | Meaning | Status |
|---|---|---|
| Approval (human-in-the-loop) | Gate blocks high-risk step until approve/deny | ✅ exists |
| Escalation (human-out-of-the-loop) | Retries exhaust → package → notify → `ESCALATED` | ❌ missing |
| Follow-up with preserved context (G4) | Operator inspects everything, optionally feeds a fix back | ❌ missing |

### 8.2 Why the retry mechanism is the crux

R3: *each retry sees prior failure history, so the agent can adapt before escalating.* This is a hard design constraint:

- **Temporal-native retries can't satisfy it.** Temporal re-runs a failed activity **with the exact same input**. The agent's second attempt starts from the same prompt as its first — it doesn't know a first attempt happened, so it repeats the same fix and fails the same way. Three retries = three identical failures. That's retry-as-a-networking-feature ("the API call timed out"), useless for "the agent's *approach* didn't work."
- **Retry-as-a-second-opinion requires an application-level loop.** When attempt 1 fails, our code catches it, records "attempt 1: restarted pod, alert still firing," and launches attempt 2 with that record *added to its input*. The agent reads it and can reason: "restarting didn't work → maybe the PVC; check disk pressure instead." After N adaptive attempts, escalate — carrying all N attempt records.
- **This merges with build item 6** (per-step retry policy): one loop governs both *how many times* to retry and *what context* each retry sees. It sits above the engine seam, so it behaves identically on Temporal and LangGraph.

### 8.3 The escalation package is nearly free

The human needs: original alert, diagnosis, every step taken, every failure. This is not a new subsystem, because of work already planned:

- Transcript store (**#2**) persists every event (tool calls, outputs, errors) to Postgres permanently.
- Audit events (**#3**) record decisions (approvals, denials, spawns).
- The §8.2 retry loop produces structured attempt records.

"Building the package" = insert one row — `escalation 4711, session X, reason: retries_exhausted` — that *references* data already in the database. The only genuinely new (optional) piece: a final LLM call that writes a short human-readable summary so the on-call engineer doesn't start from a raw transcript.

### 8.4 The notifier port — small but load-bearing

An escalation is worthless if no human hears about it. Needed: a component that pushes to where humans look (Slack channel, webhook, ticket system).

The strip-down creates a subtle hole here: today, approval requests are delivered through the session event stream **to the web UI** — which is being deleted. Post-strip-down, an approval request has *nowhere to go*, and escalation never had a delivery path. The notifier is perhaps a few hundred lines (interface + Slack + webhook implementations), but without it **both** human-interaction features are dead ends in a headless deployment. Kept as a port so each product plugs in its own (RHDH notifications, PagerDuty, plain webhook as the minimal case). Matches doc 2's "approval routing — Slack/webhook notifiers" build item; one port serves approvals *and* escalations.

### 8.5 Where escalation is expressed

Hybrid:
- **Engine-level default policy** — "retries exhausted ⇒ escalate with package" — so every blueprint is safe without authors wiring anything.
- **Optional `escalation_node` element** for custom flows — e.g. SRE case: RCA succeeded, remediation failed twice → escalate *with the RCA attached*, not just "workflow aborted."
- Policy question to settle: a **denied** high-risk approval should probably route to escalation (a human already engaged; give them the context) rather than plain failure.

### 8.6 v1 vs v2 — end at the human, or round-trip through them

**v1 (satisfies R3 as written):** retries exhaust → build package → notify → workflow ends in a new terminal state `ESCALATED` (distinct from `FAILED`: "a human now owns this"). The human fixes things manually.

**v2 (natural upgrade, G4's full form):** the workflow doesn't end — it **parks**, waiting possibly days for the human. The engineer fixes the underlying issue and replies "resolved, retry from step 3"; the *same workflow* wakes and continues with the human's note in its context. Temporal makes waiting trivially cheap (parked workflow = no resources, survives restarts); LangGraph mode rides the DB-backed gate/poller machinery from item 4.

**Design decision to make now, cheaply:** model escalation as a *state* a workflow can be in, not a hard-coded terminate — then v2 is an enhancement, not a rewrite.

---

## 9. Consolidated Build List

Beyond the strip-down itself:

| # | Item | Notes |
|---|---|---|
| 1 | Postgres repositories | Re-implement ~4 surviving ports (sessions, blueprints, resources, client config) on JSONB |
| 2 | Durable transcript store | IEM-middleware event sink → `session_events`; Redis stays live-replay transport |
| 3 | Audit events | Same middleware → typed `audit_events` |
| 4 | Durable HITL | DB-persisted approvals; Temporal: workflow signals + durable timers; LangGraph: poller. Removes 300 s cap |
| 5 | LangGraph durability | Postgres checkpointer + resume-on-startup |
| 6 | Per-step retry policy | Step-level config honored by both engines; no-retry default for high-risk steps |
| 7 | State-by-reference | Fix Temporal payload cap; pairs with #2 |
| 8 | Spawner abstraction | K8s + Podman (+ OpenShell) implementations |
| 9 | `sandbox_agent_node` | Ephemeral per-step execution via catalog extension |
| 10 | Sandbox security | TLS runner↔sandbox, credential injection, per-step tool scoping |
| 11 | Triggers | API exists; add webhook (alert) + cron (schedule) launches — R11 |
| 12 | Thin auth | Bearer + K8s TokenReview, pluggable RBAC, fail-closed — replaces Keycloak |
| 13 | OTel observability | Tracing across steps, metrics, structured logging — R10 |
| 14 | Escalation to human | App-level retry loop w/ failure history, `ESCALATED` state + package, notifier port (Slack/webhook/ticket), engine-default policy + `escalation_node`; v2 park-and-resume — see §8 |
| 15 | Podman install path | Installer profile; flip `engine_name` default to local engine |

Known remaining gaps not yet addressed by any component: agents-as-tools registry (R12, doc 2 marks "to be explored"); cross-workflow conversational memory (doc 2 backlog).

---

## 10. Deployment Profiles

| Profile | Components | Engine |
|---|---|---|
| **Small on-prem / Podman installer** | Harness + Postgres (host product's or bundled) — 1–2 containers | LangGraph + Postgres checkpoints |
| **OpenShift / scale** | Harness + Postgres + Temporal (+ Redis for streaming) | Temporal (durable timers, horizontal workers) |

Same YAML, same API, one config value apart.

---

## 11. Open Questions

1. **UnifAI as skeleton vs `lightspeed-cloud-agents` PoC as skeleton.** §7 argues UnifAI's orchestration layer wins as the base, but the PoC has already explored most of build items 8–14 (spawners, TLS, transcript store, triggers, auth). A code-maturity comparison of the PoC repo would settle how much of items 8–14 is importable rather than buildable.
2. Skills-as-OCI-images distribution mechanics (mount path, versioning) — adopt PoC approach as-is?
3. Which team owns the sandbox runtime image (`lightspeed-agentic-sandbox`) long-term?
