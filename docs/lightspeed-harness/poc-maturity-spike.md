# Spike Report: `lightspeed-cloud-agents` PoC Code Maturity (issue #5)

**Date:** 2026-07-20 · **Repo reviewed:** local checkout @ 2026-07-16 (466 commits)
**Question:** For each Phase 2–4 build item, import from the PoC or build in UnifAI/MAS?

## Overall maturity

Far beyond "explored": **~11K src LOC, ~28K test LOC (1,234 test functions — 2.5:1 test:src)**, unit/integration/e2e/load suites (spawn storms, approval backpressure, SSE scalability), helm + podman + kind deploy assets, and a **published sandbox image** (`quay.io/openshift-lightspeed/lightspeed-agentic-sandbox`). Modules are small, typed, docstringed, Pydantic-modeled.

Key architecture facts:
- **Workflow model**: `WorkflowDefinition` (apiVersion/kind YAML) with steps of type `agent` | `human-approval`, `parallel_group`, per-step `max_retries`, and a **safe condition grammar** (regex-parsed `steps.X.output.Y == v`, and/or — no eval).
- **Approvals are Temporal signals + `wait_condition`** with an auto-approve policy enforcer — exactly the durable-HITL architecture our plan item 2.2/#12 prescribes.
- **Per-attempt fresh pods**: `compute_pod_name(workflow_id, step_name, attempt)` content-hash naming; retried activities spawn fresh sandboxes.
- **Temporal-only engine.** No in-process/LangGraph-style mode exists. FastAPI router (`temporal_api.py`) fronts it.
- Escalation packages carry `failure_history`; whether each *retry attempt* sees prior failure context (R3's adaptive-retry) needs a deeper look — flagged as the one behavioral gap to verify.

## Verdict per build item

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 2 | Transcript store | **Import** | `storage/transcript_store.py` — asyncpg, auto-migrating schema, TTL cleanup, unit-tested |
| 3 | Audit events | **Import** | `workflow/audit.py` + structured_logging |
| 4 | Durable HITL | **Import the pattern** | Signals + `wait_condition` + `auto_approve.py` enforcer; port into MAS's Temporal adapter (MAS keeps its gate port for the LangGraph mode) |
| 5 | LangGraph durability | **Build** (unchanged) | PoC has no non-Temporal engine — this remains UnifAI's differentiator for the 1–2 container floor |
| 6 | Per-step retry policy | **Import + verify** | Per-step `max_retries` → Temporal RetryPolicy; attempt-hashed pods make retries safe. Verify/add failure-history injection (R3) |
| 7 | State-by-reference | **Import the pattern** | Step outputs stay small; bulk content lives in the transcript store |
| 8 | Spawner abstraction | **Import wholesale** | `spawner/` — ABC (`spawn/destroy/list_active/read_file/write_file/wait_ready`, concurrency cap) + **Kubernetes (558 LOC), Podman (335), OpenShell (1,092)** implementations, load-tested |
| 9 | `sandbox_agent_node` | **Build (thin)** | MAS catalog element wrapping the imported spawner + `/v1/agent/run` contract |
| 10 | Sandbox security | **Import** | `tls.py` (ephemeral per-sandbox CA), `content_policy.py`, `redact.py`, egress e2e tests, MCP secret allowlist |
| 11 | Triggers | **Import** | `alert_trigger.py` (547), `schedule_trigger.py` (713), both e2e-tested |
| 12 | Thin auth | **Import** | `runtime/auth.py` (397) — bearer + K8s TokenReview as FastAPI dependency; adapt to Flask or adopt FastAPI for new surface |
| 13 | OTel | **Import** | `runtime/tracing.py`, `temporal_metrics.py`, `structured_logging.py` |
| 14 | Escalation | **Import** | `escalation.py` (435) — `EscalationPackage` + pluggable packagers (Log/Webhook/**Jira**/CLIHandoff), handoff-context serializer; `notifier.py` for approvals |
| 15 | Podman installer | **Import + merge** | `deploy/podman/` assets merge into our `deploy/harness/` compose |

**Net effect on the plan:** Phases 3–4 shrink from "build ~6 major components" to "import ~10 modules + build 2 thin adapters (#9 MAS node, Flask/FastAPI auth bridge)". Phase 2 items 2.2/2.5/2.6 also switch to import-and-port. Biggest remaining genuine builds: LangGraph checkpointing (#5-item), Postgres repositories for MAS stores (#7-issue), and the retry failure-history verification.

## Strategic read (revisits analysis §11 Q1)

The two codebases are **complementary layers, not competitors**:

- **PoC** = execution substrate + governance: sandboxes, spawners, security, triggers, observability, escalation — for **linear/conditional step workflows** (diagnose → approve → fix → verify).
- **UnifAI MAS** = definition + orchestration layer: multi-agent *graphs* (orchestrator, mergers, A2A, MCP element catalog), dual engines, NDJSON streaming, session management.

Recommended integration: **MAS consumes `cloud_agents` as a library.** The `sandbox_agent_node` (#20) imports the spawner; MAS's Temporal adapter adopts the signal-based approval pattern; transcript/audit/escalation/trigger modules are imported behind MAS ports. Products whose use case is a linear workflow can run the PoC surface directly; products needing agent graphs get MAS with the same substrate underneath.

**Caveats:** PoC is asyncio/FastAPI vs MAS's Flask/sync-with-bridges — importing modules is clean (they're self-contained), but wiring needs the existing `AsyncBridge` pattern. PoC is Temporal-only — the harness-lite (no-Temporal) profile still depends on our LangGraph checkpointing work. License/ownership: same org, no blocker.
