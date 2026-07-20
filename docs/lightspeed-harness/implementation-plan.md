# Implementation Plan — Minimal Lightspeed Agent Harness (from UnifAI)

**Date:** 2026-07-20
**New here?** Start with [HANDOFF.md](HANDOFF.md) — full pick-up guide.

**Companion doc:** [stripdown-analysis.md](stripdown-analysis.md) — all rationale lives there; this doc is sequencing, priorities, and scope cuts. Build-item numbers (#1–#15) refer to the analysis doc §9.

## Status (prototype on the `lcs-main` fork line)

**Complete — M0, M1, M2, M4** (all P0 work + the product-integration surface). Delivered across PRs #29–#49, each gated by a 5-job CI lane (unit · minimal-install · headless-e2e mongo · headless-e2e postgres · temporal-replay):

- **M0** — profiles-not-deletion, feature-gating, headless E2E, PoC spike, CI lane
- **M1** — Postgres repositories, durable transcript, audit trail, Postgres-default compose
- **M2** — app-level retry w/ failure history, LangGraph Postgres checkpointer + resume-on-startup, state-by-reference (Temporal claim-check codec), escalation v1 (`ESCALATED` + package), notifier port (Slack/webhook), Temporal replay determinism test, durable HITL (DB-persisted approvals, configurable long waits)
- **M4** — triggers (alert webhook + cron/interval scheduler), thin auth (bearer + K8s TokenReview, pluggable RBAC), OTel (session spans + metrics), escalation LLM summary, Podman installer + langgraph-default flip

**Remaining — M3 (ephemeral sandbox execution, #18–#22).** Highest import-vs-build variance; per the [PoC spike](poc-maturity-spike.md) mostly *importable* from `lightspeed-cloud-agents` (spawner, sandbox image, TLS, security). Needs the published `lightspeed-agentic-sandbox` image + real Podman/K8s to verify end-to-end, so it's a distinct chunk of work best started against that infra. Deferred backlog (#28, park-and-resume / agents-as-tools / cross-workflow memory) and the quarantine burn-down (#3) remain open.

Every P0 requirement from both source docs is met on the harness profile; M3 is the sandboxed-execution model (doc 2 R4/R7/R8).

**Prioritization principles:**

1. **Persistence first.** Nearly every requirement (transcripts, audit, escalation, checkpoints, durable HITL) writes to the database — the Postgres foundation unblocks everything and is the reason nothing else can ship first.
2. **Prove the floor early.** The differentiating claim is "1–2 containers next to your product." A headless blueprint running on Podman + Postgres is the earliest demonstrable milestone, and de-risks the strip-down itself.
3. **Don't build what might be importable.** The `lightspeed-cloud-agents` PoC already explored spawners, TLS, transcript store, triggers, auth. A time-boxed comparison spike runs *before* Phase 3 commits to building.
4. **Requirements over features.** Anything not tracing to doc 1 / doc 2 R1–R12 is out of scope (no UI, no RAG, no sharing).

---

## Phase 0 — Harness Profile & Baseline (foundation, ~1–2 wk)

Goal: a **harness deployment profile** that builds, tests green, runs a blueprint end-to-end headlessly — with zero code deleted, so the full platform remains deployable in hosted environments (analysis §3 revision: profiles, not deletion).

| # | Item | Effort | Notes |
|---|---|---|---|
| 0.1 | Define the two deployment profiles: **`harness`** (MAS + DB only) and **`platform`** (all services). Helmfile selector + Podman compose file per profile. `ui/`, `rag/`, `backend/`, `identity/` are simply not deployed in `harness` | S | No deletion — they're already separate deployables |
| 0.2 | Feature-gate platform-only MAS modules for the harness profile: `sharing`, `collaboration`, `statistics`, `workspace`, `retrievers`, `actions/providers/rag` — conditional Flask endpoint registration + optional catalog elements + `pyproject` extras | M | Config-driven, not code removal; catalog auto-discovery already tolerates absent extras |
| 0.3 | MAS test suite green in **both** profiles; tag platform-only tests so the harness CI lane skips them | M | Gate for all later phases |
| 0.4 | Verify headless E2E on the harness profile: blueprint → `mas api` → execute → stream via `curl` + CLI | S | CLI is the interim human interface |
| 0.5 | **Spike: `lightspeed-cloud-agents` PoC code-maturity review** (analysis §11 Q1) | S (time-boxed) | Output: import-vs-build verdict per Phase 3/4 item. Do it now — it reshapes Phases 3–4 |
| 0.6 | **Harness-profile CI lane** — build + E2E on every PR | S | The anti-drift guarantee; non-negotiable (analysis §3 risk note) |

**Milestone M0:** harness profile deploys standalone, tests green in both profiles, headless blueprint execution demonstrated; full platform still deployable unchanged.

---

## Phase 1 — Postgres Foundation (P0, ~2–3 wk)

Goal: single-database architecture on the DB host products already run. Everything later writes here.

| # | Build item | Effort | Depends on |
|---|---|---|---|
| 1.1 | #1 Postgres repositories — sessions, blueprints, resources, client config on JSONB, **added beside the Mongo adapters** behind the existing ports; backend selected by config (harness default: Postgres; hosted platform keeps Mongo) | M | M0 |
| 1.2 | #2 Transcript store — IEM-middleware event sink → `session_events` (port + both backends, or Postgres-first with port ready) | M | 1.1 |
| 1.3 | #3 Audit events — same middleware → `audit_events` | S | 1.2 (shared sink plumbing) |
| 1.4 | Harness profile defaults: Postgres backend, no Mongo container; Redis demoted to optional (DB fallback for streaming reads at small scale) | S | 1.1 |

**Milestone M1:** harness profile = MAS + Postgres only (2 containers; 1 if host product's Postgres reused). Full transcript survives restart; `FAILED` runs leave permanent evidence. Hosted platform profile unaffected.

**Priority rationale:** P0 because §5 of the analysis shows the durability/audit/transcript goals are all *plumbing onto a database* — no later item can land without it, and it delivers the on-prem footprint story immediately.

---

## Phase 2 — Durability, Retry & Escalation (P0, ~3–4 wk)

Goal: durable/restartable/auditable workflows on **both** engines; failures reach humans. This phase is the requirement heart (R2, R3, R5, R6, G4).

| # | Build item | Effort | Depends on |
|---|---|---|---|
| 2.1 | #6 + §8.2 App-level retry loop with failure-history injection; per-step retry policy in blueprint schema (no-retry default for high-risk) | M | M1 |
| 2.2 | #4 Durable HITL — approvals persisted in DB; Temporal: lift gates out of activities into signals + durable timers; LangGraph: DB poller. Removes 300 s cap and 120-min activity ceiling | L | M1 |
| 2.3 | #5 LangGraph durability — Postgres checkpointer + resume-on-startup scan | M | M1 |
| 2.4 | #7 State-by-reference — bulk state/transcript content in DB, references through engine payloads (fixes Temporal ~2 MB cap) | M | 1.2 |
| 2.5 | #14 Escalation v1 — `ESCALATED` state (modeled as state, not hard-coded terminate), package record, engine-default policy, optional `escalation_node` | M | 2.1, 1.2, 1.3 |
| 2.6 | Notifier port + Slack & webhook implementations (serves approvals *and* escalations — §8.4) | M | 2.2, 2.5 |
| 2.7 | Temporal replay test in CI (mitigates `UnsandboxedWorkflowRunner` risk) | S | 2.1–2.2 |

**Milestone M2:** kill a worker mid-run on either engine → workflow resumes; approval waits survive days; exhausted retries produce a notified, fully-packaged escalation.

**Priority rationale:** P0 — this is what "harness" means per both requirement docs. Sequenced after Phase 1 because every item persists state. 2.1 before 2.5 (escalation consumes attempt records); 2.2 and 2.6 together close the "headless approvals have nowhere to go" hole opened by deleting the UI.

---

> **Spike outcome (2026-07-20, [poc-maturity-spike.md](poc-maturity-spike.md)):** the `lightspeed-cloud-agents` PoC is production-shaped (11K src / 28K test LOC, 3 spawner impls, signal-based approvals, transcript store, triggers, TLS, escalation w/ packagers). Verdict: **import ~10 modules, build 2 thin adapters.** Phases 3–4 below shift from build-first to import-and-port; Phase 2 items 2.2/2.5/2.6 adopt the PoC's signal pattern and escalation/notifier modules. Genuine builds that remain: LangGraph checkpointing (2.3), MAS Postgres repositories (1.1), retry failure-history verification (2.1).

## Phase 3 — Ephemeral Sandbox Execution (P1, ~4–6 wk, shaped by Phase 0.5 spike)

Goal: doc 2's R4/R7/R8 execution model — fresh sandbox container per agent step — as a catalog extension, engines untouched.

| # | Build item | Effort | Depends on |
|---|---|---|---|
| 3.1 | #8 Spawner port (`spawn/await/destroy/reconcile`) + **Podman** implementation first (proves the installer profile), then K8s | L | M2; spike verdict |
| 3.2 | Sandbox runtime image — adopt `lightspeed-agentic-sandbox` (`/v1/agent/run` contract) rather than extract from UnifAI nodes | M (adopt) / L (build) | Spike verdict |
| 3.3 | #9 `sandbox_agent_node` element — supervisor-style execution (spawn → run → collect structured output → destroy); content-hash naming for idempotent retries; orphan reconciliation wired to resume-on-startup | M | 3.1, 3.2 |
| 3.4 | #10 Sandbox security — runner↔sandbox ephemeral TLS, network-level credential injection, per-step tool allow/deny | L | 3.1–3.3; heavily importable per spike |
| 3.5 | In-sandbox events forwarded to IEM stream (live streaming parity) | S | 3.3 |

**Milestone M3:** an agent step runs in a fresh sandbox on Podman and on K8s; retry spawns a fresh container; credentials never enter the agent process.

**Priority rationale:** P1, not P0 — the harness is *useful* after M2 (in-process agent nodes still work, incl. `claude_agent`), and this phase has the highest import-vs-build variance. Deliberately after Phase 2 so retries/escalation/HITL semantics are settled before the execution substrate changes beneath them.

---

## Phase 4 — Product Integration Surface (P1, ~2–3 wk, parallelizable with Phase 3)

Goal: what embedding products and installers touch.

| # | Build item | Effort | Depends on |
|---|---|---|---|
| 4.1 | #11 Triggers — webhook (alert) + cron (schedule) workflow launches; Temporal Schedules on that profile, DB-poller cron on light profile | M | M2 |
| 4.2 | #12 Thin auth — bearer + K8s TokenReview middleware, pluggable RBAC, fail-closed | M | M0 (replaces Keycloak) |
| 4.3 | #13 OTel — tracing across steps (and into sandboxes when M3 lands), Prometheus metrics, structured logs | M | M2 |
| 4.4 | #15 Podman installer profile — package/compose definition, flip `engine_name` default to local engine, install docs | M | M1 |
| 4.5 | #14/§8.3 Escalation summary step (LLM-written on-call summary) | S | 2.5 |

**Milestone M4 (integration-ready):** a product team can install via Podman or Helm, define a workflow YAML, trigger it from an alert webhook or schedule, authenticate calls, observe via OTel, and receive approvals/escalations in Slack — with no UnifAI-platform remnants.

**Priority rationale:** P1 — required for any real product embedding, but every item is independent surface area; safe to parallelize with Phase 3 and to staff separately. 4.1 is first among equals: proactive workflows are in every target use case.

---

## Phase 5 — Deferred (P2, post-integration)

| Item | Why deferred |
|---|---|
| Escalation v2 park-and-resume (§8.6) | v1 satisfies R3; state-not-terminate decision in 2.5 keeps this an enhancement |
| #R12 Agents-as-tools registry → LLM tool generation | Doc 2 marks "to be explored"; needs a consuming chatbot to design against |
| Cross-workflow conversational memory | Doc 2 backlog; no target use case blocks on it |
| Additional spawner backends (OpenShell VM, etc.) | Port design in 3.1 makes these additive |
| Per-workflow engine selection | No requirement; keeps support matrix simple |

---

## Critical Path & Sequencing Summary

```
M0 strip-down ──► M1 Postgres ──► M2 durability/escalation ──► M3 sandboxes ──► GA-ready
                        │                                          ▲
                        └────────► M4 integration surface ─────────┘ (parallel with M3)
     Phase 0.5 PoC spike ─────────────── informs ──────────────► Phase 3 & 4 scope
```

- **Longest pole:** Phase 2.2 (durable HITL rework — touches both engines) and Phase 3.1/3.4 (spawner + security). Start the PoC spike immediately to shrink the latter.
- **Earliest demo:** M1 (2 containers, full transcripts) — the on-prem footprint story, ~3–5 weeks in.
- **Requirement coverage:** M2 closes doc 1's core capabilities + R2/R3/R5/R6; M3 closes R4/R7/R8; M4 closes R9/R10/R11 + both deployment targets. R12 deferred by design.

## Top Risks

| Risk | Mitigation |
|---|---|
| **Profile drift** — harness profile regresses while development targets the full platform | Harness CI lane on every PR (0.6); harness-profile E2E as release gate |
| **Dual persistence backends** (Mongo + Postgres) double the storage test matrix | Ports already exist; contract-test suite runs against both backends; new stores (transcript/audit/checkpoints) are Postgres-first with a port |
| PoC comparison flips the skeleton decision (analysis §11 Q1) | Phase 0.5 spike before any Phase 3 investment; Phases 0–2 are valuable under either skeleton |
| Durable-HITL rework (2.2) destabilizes the Temporal path | Keep old gate path behind a flag until replay test (2.7) is green |
| At-least-once node execution re-runs side-effectful steps | No-retry default for high-risk steps (2.1) lands *before* resume-on-startup (2.3) is enabled by default |
| Payload-cap regressions with long transcripts | 2.4 state-by-reference gated by an integration test with a large synthetic transcript |
