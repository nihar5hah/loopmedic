# LoopMedic — Final Project Plan

**Grounded runtime supervision and recovery for a stateful tool-using LLM agent.**

A supervisor sits between an agent and its tools, watches what the agent actually
does to a real database, detects when the agent is stuck or about to do something
unsafe (like a duplicate booking), and applies a targeted recovery action.
Evaluated with deterministic database invariants, not LLM judges.

Status: **frozen**. This version reconciles all design reviews. No further
paper-only revisions — remaining unknowns are settled by the Week 1–2 spikes.

---

## 1. What we are building (locked scope)

Five components, one Python subprocess per run, SQLite, no Docker, no microservices.

| # | Component | What it is |
|---|-----------|------------|
| 1 | **Appointment environment** | SQLite-backed booking domain exposed as MCP tools |
| 2 | **Supervisory MCP facade** ("gateway") | The MCP server the agent connects to: records traffic, injects faults, attaches correlation ids, consults LoopMedic, calls the domain service in-process |
| 3 | **LoopMedic core** | Trace store, state hashing, detectors, recovery controller |
| 4 | **Agent runner** | OpenAI Agents SDK agent connected to the facade, with lifecycle hooks feeding LoopMedic |
| 5 | **Evaluation + dashboard** | Deterministic invariant evaluator and experiment runner first; custom trace UI last, after the matrix |

### Explicitly cut (do not build, mention as future work in report)

- Learned/ML failure classifier
- Model escalation, tool-set reduction, context repair, checkpoint/rewind
- Claude Code adapter, voice frontend
- Self-reflection baseline, "always stronger model" baseline
- Separate FastAPI supervisor service, Docker Compose, PostgreSQL
- Building the dashboard before Phases 1–8 (core logic, then experiments)
- Semantic (embedding-based) repetition detection — normalized signatures only
- Privacy/telemetry tiers (all data is fictional and local)
- Partial-response and schema-ambiguity faults

---

## 2. Architecture

```
User task
    |
    v
OpenAI Agents SDK runner
    |  lifecycle hooks ──────────────────────────────> LoopMedic
    |  (llm start/end, final output, budgets)              |
    |                                                      | reject completion
    | MCP (streamable HTTP, localhost)                     | (harness-level)
    v                                                      |
Supervisory MCP facade  <──────── allow / block+feedback ──┘
    |  before/after every tool call (reads and writes)     ^
    |  record request/response                             |
    |  attach correlation ids                              |
    |  fault injector (seeded)                             |
    |  on observed timeout: verify-on-loss ────────────────┘
    |  in-process call
    v
Appointment domain service (Python API + SQLite)
    |
    v
State snapshot + canonical hash after every tool call ──> LoopMedic
```

The experiment runner launches one Python subprocess per run, containing a
single event loop. The facade is a real MCP server on localhost, so the Agents
SDK connects to it like any MCP server. It is *not* an MCP-to-MCP proxy: it
calls the domain service directly in-process (no second MCP hop). The report
should call it a supervisory facade, not a proxy.

**All three experimental conditions use this same facade.** Faults, recording,
and state snapshots are identical everywhere. The only difference is the
intervention policy: A always allows, B blindly retries each tool error once,
C lets LoopMedic decide.

---

## 3. Locked design decisions

1. **Ledger identity is two-part, written transactionally.** Every executed
   tool call gets a unique `attempt_id`. Every write also gets a stable
   `operation_fingerprint = hash(run_id, tool, target entity)` — e.g.
   `create_appointment` + customer + slot — used to match retries even when
   argument details drift (a retry that drops `hold_id` still matches). The
   ledger row (`attempt_id`, `fingerprint`, `tool`, `status`, `result_ref`)
   is committed **in the same SQLite transaction as the domain write**, so
   ledger and world state can never disagree.

2. **The ledger is observational, not an enforcer.** The environment does
   **not** reject a second write with a matching fingerprint. If it did,
   duplicate bookings would be impossible and the headline demo would be
   fake. LoopMedic is the only thing that prevents duplicates, which is the
   point of the experiment.

3. **The environment is explicitly non-idempotent.** Three guarantees make
   the duplicate-booking failure physically possible:
   - `create_appointment` does **not** consume the hold; the hold stays
     ACTIVE until it expires or is explicitly released.
   - Slot capacity is ≥ 2 in faulted scenarios.
   - There is no customer+slot uniqueness constraint on appointments.
   A blind retry after a lost response therefore really creates a second
   CONFIRMED appointment.

4. **Unknown-commit handling: proactive first, reactive as backup.**
   - *Proactive (primary):* when the facade observes a write time out, in
     condition C LoopMedic immediately checks the ledger. If the write
     committed, the agent receives a verified synthetic success ("the
     operation succeeded; appointment A31 exists") instead of the timeout.
     Deterministic — no dependence on what the agent decides to do next.
   - *Reactive (defense-in-depth):* if a proposed write matches a SUCCEEDED
     fingerprint, block it and return the verified ledger answer.
   - *Fairness constraint:* LoopMedic keys off the **observed timeout** — the
     same signal the agent sees — never off the fault injector's internal
     state. The supervisor gets no oracle knowledge that a fault was injected.

5. **Logical time only.** The environment has a step counter advanced on each
   tool call. Hold expiry, `created_at`, and everything used by invariants are
   in logical steps. No wall-clock dependence → fully reproducible runs.

6. **Canonical state hash includes derived state.** Hash of sorted domain
   rows with volatile columns (ledger timing, raw step counters) excluded —
   but **effective values are materialized first**: a hold's status is
   snapshotted as ACTIVE or EXPIRED as of the current step, so logical time
   passing can change the hash. Without this, stagnation detection goes blind
   to expiry. Gets a dedicated unit test suite before any detector is written.

7. **`version` on appointments is optional optimistic concurrency.**
   `cancel_appointment` accepts an optional `expected_version`; omitted →
   write proceeds, provided-and-mismatched → rejected. Making it required
   would tank clean success whenever the model forgets it, which is not the
   failure class this project studies.

8. **Safety invariants are evaluated over history, not final state.** The
   final database cannot prove "the old appointment was never cancelled
   before the replacement was secured." The evaluator walks the sequence of
   per-call state snapshots (already stored in the trace) and checks ordering
   properties there. Final-state invariants cover the rest.

9. **Supervision conditions are honestly named.** Three measured conditions
   (§7). "MCP-only vs full-harness" is a qualitative discussion point
   (premature completion is invisible without harness hooks), not a measured
   fourth condition.

10. **Completion-rejection is spiked first and tested scripted.** Rejecting a
    final answer and forcing continuation is the least-standard SDK mechanism
    in the design: validated in Week 1 with a toy agent; guardrail-based
    fallback decided by end of Week 2. The mechanism also gets a
    **deterministic scripted-agent test** (a fake agent that declares success
    with invariants unmet), so correctness never depends on coaxing a real
    model into failing.

11. **Every run gets a fresh database.** Each run starts from its own copy of
    the pristine seeded SQLite file. Runs are sequential (120 × 1–2 min is a
    few hours; parallelism buys nothing but port and log confusion).

12. **Hard rules vs heuristics.** Unknown-commit and premature-completion
    fire on a single signal and take priority. Repetition, stagnation, error
    streaks, and budget require ≥ 2 corroborating signals. The 2-signal rule
    exists so LoopMedic does not nag a healthy agent.

13. **Recovery-budget exhaustion stops intervening, it does not kill the
    run.** After 2 recoveries, calls pass through. Hard-stop only if a safety
    invariant is already broken and another write would worsen it, or the
    global tool-call cap is hit.

14. **Global tool-call cap is 15 in every condition**, counting every
    agent-requested call including blocked ones. Blocked calls do not reach
    the environment, so C can be cheaper on side-effects within the same
    visible budget.

15. **Models come from OpenCode Go via the OpenAI Agents SDK.** The SDK is
    not OpenAI-hosted-only: pass `AsyncOpenAI(base_url=..., api_key=...)`.
    Go is **not** one API for every model — pick the matching wire format
    (see §7). Do not switch harnesses.

16. **Dashboard is last.** Phases 1–8 (environment, runner, facade,
    detectors, recovery, 120-run matrix) ship before any UI. Phase 9 is a
    custom trace viewer over already-written JSON traces.

---

## 4. The environment (domain)

Fictional appliance-service appointment system.

**Entities:** `customers`, `appointments` (CONFIRMED / CANCELLED / COMPLETED,
with `version`), `slots` (capacity ≥ 2 in faulted scenarios), `holds`
(separate entity; ACTIVE until released or expired; default TTL 30 logical
steps, above the 15-call cap), `notifications`, `operation_ledger`
(observational; see §3.1).

Appointment status is **not** called HELD — that name is reserved for slot
holds, which are a different entity.

**Tools (10):**

| Read | Write |
|------|-------|
| `get_customer` | `hold_slot` |
| `list_customer_appointments` | `release_hold` |
| `search_available_slots` | `create_appointment` |
| `get_appointment` | `cancel_appointment` |
| `get_booking_policy` | `send_confirmation` |

No shortcut `reschedule_appointment` tool — rescheduling requires coordinating
search → hold → create → cancel → confirm, which produces real multi-step
trajectories.

**Write rules that stay simple:**
- `create_appointment` requires a valid, unexpired hold for that customer+slot
  and creates a CONFIRMED appointment. It does **not** consume the hold (§3.3).
- `send_confirmation` creates a notification row; fails if the appointment
  does not exist.
- `cancel_appointment` is allowed by default policy. `get_booking_policy`
  returns a short, stable policy document — no maze of exceptions.

**Task families:** booking, rescheduling, cancellation — parameterized
templates with seeded randomness. One conflict-style scenario: requested slot
unavailable; success = original appointment intact, user informed.

**Invariants:** final-state (e.g. exactly one active appointment; new
appointment on requested day/period; old appointment cancelled; confirmation
sent) plus history-based safety invariants over the snapshot sequence (§3.8):
no duplicate booking at any point; old appointment never cancelled before the
replacement existed; no confirmation for a nonexistent appointment.

---

## 5. Faults (4, all seeded and deterministic)

| Fault | Behavior | Correct recovery |
|-------|----------|------------------|
| Pre-execution timeout | Tool never executes; agent sees timeout | Safe retry |
| **Post-commit response loss** | Write succeeds; response replaced by timeout | Verify ledger, return verified result (headline demo) |
| Stale read | Read returns a previous state version | Refresh guidance |
| Transient error | First call fails, later call succeeds | Bounded retry |

Config: `{fault_type, target_tool, trigger_on_call, seed}` per scenario.

**Stale-read scope (resolved):** with `expected_version` optional, stale-read
scenarios measure *decision-quality harm* (the agent acting on wrong
information), not write corruption. LoopMedic's contribution there is refresh
guidance. The report must not claim more.

**What conditions B and C do with the same timeout (the actual comparison):**
- **B (blind retry):** the facade retries every tool error/timeout **once**,
  returns the second result. On post-commit loss, that automatic retry *is*
  the duplicate booking.
- **C (LoopMedic):** on an observed timeout, check the ledger. Did not
  execute → safe retry. Did execute → return the verified result instead
  (proactive path, §3.4); if the agent later re-proposes a matching write
  anyway, block it (reactive path). Same observable signal, different
  knowledge — that difference is the project.

---

## 6. Detection and recovery (locked set)

**Detectors** (evaluated after every event, evidence stored in trace):

1. Exact repetition — same canonical tool signature repeated
2. Same-error streak — identical normalized error, no state/argument change
3. State stagnation — N steps without state-hash change
4. **Unknown commit** — observed timeout on a write whose ledger status is
   SUCCEEDED (proactive), or a proposed write matching a SUCCEEDED
   fingerprint (reactive)
5. Premature completion — final output proposed while required invariants fail
6. Budget monitor — tool-call / token budget fraction consumed

**Recovery actions:**

1. **Soft feedback** — wrap the tool result with a grounded note ("last two
   calls returned identical results; state unchanged")
2. **Verified result substitution** — on unknown commit, replace the timeout
   with the ledger-verified outcome (proactive)
3. **Block duplicate write** — do not forward; return the verified ledger
   answer (reactive)
4. **Reject completion** — harness-level: unmet invariants go back to the
   model, run continues
5. **Safe retry** — facade retries once, only when the ledger says the
   operation did not execute
6. **Stop intervening** — recovery budget (2) exhausted; calls pass through
7. **Hard-stop** — only if a safety invariant is already broken and another
   write would worsen it, or the 15-call cap is hit

**False-intervention controls:** writes get stricter treatment than reads;
unknown-commit and premature-completion are single-signal hard rules; the
rest need ≥ 2 signals; cooldown of 2 steps after any intervention; every
policy also runs against clean tasks.

---

## 7. Experiment (locked matrix)

| Condition | Description |
|-----------|-------------|
| A — None | Facade always allows; faults still injected |
| B — Fixed retry | Facade retries every tool error/timeout once; cap 15 |
| C — LoopMedic | Targeted recovery using ledger + state + harness hooks |

- **20 scenarios** (12 faulted across the 4 fault types + 8 clean controls)
- **× 3 conditions × 2 repetitions × 1 model = 120 runs**
- Model: OpenCode Go default `deepseek-v4-flash` (Chat Completions).
  `muse-spark-1.2-contributor` is the Responses-API fallback. Override with
  `LOOPMEDIC_MODEL`. Second model = stretch.
- **Go endpoints** (`https://opencode.ai/docs/go/`):
  - `https://opencode.ai/zen/go/v1` + **Chat Completions**
    (`OpenAIChatCompletionsModel`) — GLM, Kimi, DeepSeek, MiMo, Hy3.
    This is the experiment path.
  - Same base URL + **Responses API** (SDK default) — `grok-4.5`,
    `gpt-5.6-luna`, `muse-spark-1.2-contributor` only.
  - `/v1/messages` (Anthropic) — MiniMax, Qwen. **Do not use** unless we
    add LiteLLM; the OpenAI client will not hit that path.
- Auth: `OPENCODE_API_KEY` (or `OPENAI_API_KEY` pointed at Go). Disable
  Agents SDK tracing unless a real OpenAI platform key exists
  (`set_tracing_disabled(True)`).
- Phase 2 includes a one-call **tool-calling spike** against Go before any
  10-run baseline.
- Conditions **matched on scenario + fault seed**; model nondeterminism is
  handled by repetitions, not eliminated.
- Fresh database per run; runs sequential.

**Metrics:** task success rate; safety-violation rate (from history-based
invariants); recovery rate (A-failing runs that C recovers); **clean
intervention rate** (how often C intervenes on clean scenarios) and **clean
success delta** (A vs C success on the 8 clean scenarios) — reported as two
separate numbers, without claiming every A-success/C-failure pair was caused
by the intervention; duplicate writes prevented; agent-requested vs
environment-forwarded tool calls (B's hidden retry shows up in the second);
tokens.

---

## 8. Repository layout

```
minorproject/
├── PLAN.md
├── pyproject.toml
├── loopmedic/
│   ├── environment/      # SQLite schema, seed data, domain service, logical clock
│   ├── facade/           # MCP server, fault injector, correlation ids
│   ├── core/             # events, trace store, state hash, detectors, recovery
│   ├── runner/           # Agents SDK agent, lifecycle hooks, recovery packets
│   ├── evaluation/       # invariants (final + history), task templates, metrics
│   └── dashboard/        # Custom UI last (Phase 9); not before experiments
├── scenarios/            # YAML task + fault definitions
├── experiments/          # experiment configs + results (gitignored DBs)
└── tests/                # incl. scripted-agent tests for demos 2–4
```

**Stack:** Python 3.12, OpenAI Agents SDK + OpenCode Go (`base_url` + API
key), official MCP Python SDK (FastMCP), stdlib `sqlite3` (no SQLAlchemy),
Pydantic, pytest. YAML config, explicit seeds everywhere. Dashboard UI is
Phase 9 only.

---

## 9. Twelve-week timeline (with acceptance criteria)

Calibrated for one person working part-time; compress if the team is larger.

| Weeks | Work | Done when |
|-------|------|-----------|
| 1 | Repo setup; DB schema + seed data; logical clock; **spike: completion-rejection in Agents SDK** | Toy agent's final answer can be rejected and the run continued |
| 2 | Domain service + MCP tools (10); transactional ledger; invariant evaluator (final-state) | Hand-driven tool calls complete a reschedule; evaluator scores it |
| 3 | Baseline agent through the SDK (local function tools wrapping the same Python API is fine; MCP transport comes in week 5) | ≥ 90% success over 10 clean booking + reschedule runs |
| 4 | Event schema, trace store, **canonical state hash incl. derived hold status + unit tests**; history-based safety invariants | Every run replayable as a timeline; hash stable and expiry-sensitive |
| 5 | Facade: MCP server, recording, correlation ids | Agent completes all clean tasks *through the facade* |
| 6 | Fault injector (4 faults, seeded) | Each fault reproduces from its seed; a **scripted** double `create_appointment` after post-commit loss produces two appointments (no LLM involved in this check) |
| 7 | Detectors 1–4 + 6 | Detector outputs + evidence stored on every trace |
| 8 | Recovery controller: verified-result substitution, block, safe retry, soft feedback, budget, cooldowns | Scripted test: lost response → verified substitution → no duplicate; and forced-retry path → block fires |
| 9 | Premature-completion detection + rejection; recovery packet | **Scripted** false-"done" is rejected and run continues; then reproduced once with the real model |
| 10 | Run the 120-run matrix; fix what breaks (something will) | Metrics table generated from config, reproducibly |
| 11 | Custom dashboard last: run list, timeline, state diff, intervention explanation; tune clean intervention rate | Clean success delta ≈ 0; dashboard demo-ready |
| 12 | Report (problem, design, implementation, experiment setup, results, limitations, future work), demo rehearsal, buffer | — |

Weeks 10–12 are protected. If earlier weeks slip, cut scenarios (20 → 12),
never the experiment weeks.

---

## 10. Demo script (5–8 min, what the panel sees)

1. **Clean run** — agent reschedules an appointment normally; timeline view.
2. **Failure with blind retry (B)** — post-commit response loss → facade
   retries once → **duplicate booking**, shown in the state diff. (B, not A:
   A only duplicates if the model itself retries; B makes it guaranteed.)
3. **Same failure with LoopMedic (C)** — ledger checked on the observed
   timeout, verified result returned, no duplicate, task completes. The
   headline moment.
4. **Premature completion** — model claims success; LoopMedic rejects it with
   the unmet invariants; agent finishes the job. **Backup:** replay of a
   recorded run, since a live model may not fail on cue.
5. **Metrics** — success / safety / clean-run table across A, B, C.

---

## 11. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Completion-rejection infeasible in SDK | Week-1 spike; guardrail fallback decided by Week 2 |
| Streamable HTTP MCP awkward in-process | Fallback: stdio transport, or function-tool wrappers around the same facade logic |
| State hash misses expiry-driven change | Derived hold status materialized into snapshots; unit-tested Week 4 |
| Demo moments depend on LLM mood | Every demo mechanism has a scripted deterministic test; live demos have recorded replays as backup |
| Agent too good — recovers by re-reading after timeout | Demo 2 uses B (forced retry); error text is a tuning knob; if A rarely duplicates, report that as a finding |
| Agent too bad — fails clean tasks | Simplify templates / strengthen instructions until clean success ≥ ~90% before experiments |
| Interventions harm clean runs | Hard rules vs 2-signal heuristics, cooldowns; clean intervention rate + clean success delta tracked from Week 8 |
| API cost | 120 sequential runs × ~10–15 calls on a cheap model is cheap; seeds mean no wasted reruns |

---

## 12. One-paragraph summary (for the report intro)

LoopMedic is a runtime supervision layer for a tool-using LLM agent operating
a fictional appointment system through MCP. A supervisory MCP facade records
and mediates every tool call and injects reproducible faults; harness
lifecycle hooks expose model calls and final-output attempts. LoopMedic
compares the agent's behavior against verified database state and a
transactional operation ledger, detects repetition, stagnation, unknown
commits, and premature completion, and applies bounded targeted recovery —
substituting ledger-verified results for lost responses, retrying only writes
that never executed, blocking duplicate writes, and rejecting false completion
claims. Evaluation uses deterministic final-state and history-based invariants
over a 120-run experiment matched on scenario and fault seed, comparing no
supervision, blind retry, and LoopMedic on task success, safety violations,
recovery rate, and clean-run impact.
