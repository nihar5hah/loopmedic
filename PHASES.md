# LoopMedic — Implementation Phases

Companion to `PLAN.md` (frozen design). This file says what gets built, in
what order, with concrete deliverables and exit criteria per phase. Phases map
to the 12-week timeline but are sequenced by dependency, not calendar: finish
a phase's exit criteria before starting the next, even if the week slips.

```
P0 scaffold+spikes → P1 environment → P2 baseline agent → P3 tracing
      → P4 facade → P5 faults → P6 detectors → P7 recovery
      → P8 experiments → P9 dashboard+tuning → P10 report+demo
```

---

## Phase 0 — Scaffold and de-risking spikes (Week 1)

**Goal:** a runnable skeleton, and answers to the two questions that could
sink the design.

**Build:**

- `pyproject.toml` — deps: `openai-agents`, `mcp`, `pydantic`, `streamlit`,
  `pytest`, `pyyaml`. Python 3.12. Package `loopmedic/` with empty submodules
  matching the repo layout in PLAN §8.
- `loopmedic/environment/schema.sql` — full DDL:
  - `customers(customer_id, name, timezone, service_plan)`
  - `appointments(appointment_id, customer_id, slot_id, service_type,
    day, period, status, version, created_step, cancelled_step)`
    — status ∈ CONFIRMED/CANCELLED/COMPLETED, **no** customer+slot unique
    constraint (PLAN §3.3)
  - `slots(slot_id, service_type, day, period, capacity)` — capacity ≥ 2
  - `holds(hold_id, slot_id, customer_id, created_step, ttl_steps, released)`
    — effective status derived from current step (PLAN §3.6)
  - `notifications(notification_id, customer_id, appointment_id, type)`
  - `operation_ledger(attempt_id, fingerprint, tool, status, result_ref,
    step)` (PLAN §3.1)
  - `world_meta(step)` — the logical clock
- `loopmedic/environment/seed.py` — deterministic seeded generator →
  `pristine.db`. Same seed ⇒ byte-identical DB.
- **Spike A (critical): completion-rejection.** Toy Agents SDK agent, no MCP.
  Try, in order: (1) output guardrail raising with structured feedback, then
  re-running `Runner.run` with the previous result's `to_input_list()` plus a
  correction message; (2) plain re-invocation with an appended user-role
  recovery packet. Record which works and how many lines it costs.
- **Spike B: MCP transport.** Minimal FastMCP server with one echo tool,
  served over streamable HTTP from an asyncio task in the same process;
  Agents SDK `MCPServerStreamableHttp` connects and calls it. If painful,
  test stdio fallback now, not in Phase 4.

**Exit criteria:**
- `pytest` runs green on a trivial test; `seed.py` twice ⇒ identical files.
- Spike A: a toy agent's final answer is rejected and the continued run
  produces a different final answer. Mechanism written down in `PHASES.md`
  under this phase (1–2 sentences).
- Spike B: agent calls the echo tool over the chosen transport.

**Spike results:**
- A — An `@output_guardrail` that trips on the premature final answer raises
  `OutputGuardrailTripwireTriggered`. Continuation is `run_data.input` plus
  each `new_items[].to_input_item()`, then a user-role recovery message,
  passed to a second `Runner.run`. Proven with a scripted `Model` (no API key).
- B — mcp 2.0 `MCPServer` (replaces FastMCP) `streamable_http_app` served by
  uvicorn in the same event loop; `MCPServerStreamableHttp` lists and calls
  `echo` at `http://127.0.0.1:<port>/mcp`. Stdio fallback not needed.

---

## Phase 1 — Domain service, MCP tools, evaluator (Week 2)

**Goal:** the world exists and can be judged, with no LLM anywhere.

**Build:**

- `loopmedic/environment/service.py` — pure-Python domain API, one function
  per tool, each taking a DB connection:
  - every call advances `world_meta.step` by 1
  - every **write** takes `attempt_id` + `fingerprint` params and commits its
    ledger row in the same transaction as the domain change (PLAN §3.1)
  - `create_appointment` validates the hold (exists, same customer+slot,
    not released, not expired at current step) and does **not** consume it
  - `cancel_appointment(expected_version=None)` — optional optimistic check
  - `send_confirmation` fails on nonexistent appointment
  - `get_booking_policy` returns a short static policy text
- `loopmedic/environment/mcp_server.py` — FastMCP server exposing the 10
  tools (schemas only; the facade will front this in Phase 4).
- `loopmedic/evaluation/tasks.py` — task spec model: goal text, customer,
  requested day/period, list of required invariant names, scenario seed.
- `loopmedic/evaluation/invariants.py` — final-state invariants as named
  functions over a DB connection: `exactly_one_active_appointment`,
  `new_appointment_matches_request`, `old_appointment_cancelled`,
  `confirmation_sent`, `no_duplicate_booking_final`.
- `tests/test_environment.py` — includes: double `create_appointment` with
  the same customer+slot and a live hold **succeeds twice** (proves §3.3
  non-idempotency); ledger row and appointment appear/disappear atomically
  when a transaction is aborted mid-write.

**Exit criteria:** a scripted (non-LLM) tool-call sequence performs a full
reschedule on a fresh DB and the evaluator returns all-invariants-pass;
the non-idempotency test passes.

---

## Phase 2 — Baseline agent (Week 3)

**Goal:** a real model completes clean tasks. No supervision, no MCP yet.

**Build:**

- `loopmedic/runner/agent.py` — agent definition: instructions (role, task
  framing, "verify before you finish" *not* included — that's LoopMedic's
  job), model config via OpenCode Go (`AsyncOpenAI` with
  `base_url=https://opencode.ai/zen/go/v1` and `OPENCODE_API_KEY`;
  default model `deepseek-v4-flash` via Chat Completions
  (`muse-spark-1.2-contributor` is the Responses-API fallback);
  `LOOPMEDIC_MODEL` overrides; tracing disabled unless an OpenAI platform key exists), function tools that wrap
  `service.py` directly. First action: a one-call tool-calling spike against
  Go (prove tools work) before the 10-run baseline.
- `loopmedic/runner/run.py` — single-run entrypoint: make `run_id`, copy
  `pristine.db` → `runs/<run_id>.db`, run the agent with a 15-call cap,
  invoke the evaluator, print verdict. This entrypoint survives unchanged
  through all later phases; only the tool wiring changes.

**Exit criteria:** ≥ 90% success over 10 clean booking + reschedule runs.
If below, iterate on instructions/templates now — Phase 8's clean-control
baseline depends on this.

**Results:**
- Tool spike: `deepseek-v4-flash` (Chat Completions) and
  `muse-spark-1.2-contributor` (Responses) both return tool results after
  the Go China-hosting opt-in. Default stays `deepseek-v4-flash`. Function
  tools are `async` so SQLite stays on the event-loop thread.
- Baseline: **10/10** clean runs (5 reschedule + 5 booking). Typical tool
  counts: 7 for reschedule, 5 for booking.

---

## Phase 3 — Tracing and state hash (Week 4)

**Goal:** every run becomes a replayable, hashable record. Built before the
facade so the facade has somewhere to write from day one.

**Build:**

- `loopmedic/core/events.py` — `TraceEvent` (Pydantic): run_id, event_id,
  step_index, source (harness|facade|environment), event_type (run_started,
  llm_started, llm_completed, tool_proposed, tool_completed, tool_failed,
  intervention, final_output_proposed, run_completed), tool_name, arguments,
  result, error, state_hash_before/after, tokens, injected_fault.
- `loopmedic/core/trace_store.py` — separate SQLite file per experiment;
  tables `runs`, `trace_events`, `state_snapshots`, `detector_outputs`,
  `interventions`.
- `loopmedic/core/state_hash.py` — canonical snapshot: sorted rows of the
  five domain tables, ledger excluded, **hold status materialized as
  ACTIVE/EXPIRED/RELEASED at the current step** (PLAN §3.6; released is a
  distinct effective state); SHA-256 over canonical JSON.
- `loopmedic/evaluation/history.py` — history-based safety invariants over
  the snapshot sequence (PLAN §3.8): `never_two_active_appointments`,
  `old_never_cancelled_before_replacement_existed`,
  `no_confirmation_without_appointment`.
- `tests/test_state_hash.py` — key ordering doesn't change hash; irrelevant
  ledger churn doesn't change hash; **advancing the step past a hold's TTL
  does change it**; identical logical states from different call orders hash
  equal.
- Harness lifecycle hooks (`RunHooks`) wired in `runner/` to emit llm/tool
  events into the trace store.

**Exit criteria:** a Phase 2 run replays as an ordered event timeline from
the trace DB alone; all hash tests pass; history invariants correctly flag a
hand-built bad sequence (duplicate mid-run, cancel-before-replacement).

**Results:**
- Canonical hash omits the ledger and raw step counters; hold status is
  materialized as ACTIVE, EXPIRED, or RELEASED. Unit tests cover key order,
  ledger churn, TTL expiry, release-after-expiry, and read-order stability.
- History invariants flag same-slot duplicate booking, cancel-before-
  replacement, and confirmation for a missing appointment. A clean
  create-then-cancel overlap on different slots still passes.
- `RunHooks` write `runs/<run_id>.trace.db`. Function tools run serially
  (`max_function_tool_concurrency=1`). Domain errors and raised calls emit
  terminal `tool_failed` events. A scripted Phase 2 run replays as
  `run_started` → llm/tool events → `run_completed` from that file alone.

---

## Phase 4 — Supervisory facade (Week 5)

**Goal:** the agent talks MCP to the facade; the facade owns the tool
boundary.

**Build:**

- `loopmedic/facade/server.py` — FastMCP server that republishes the 10 tool
  schemas and on each call: emit `tool_proposed` → consult the intervention
  policy (Phase 7; for now a pass-through `AlwaysAllow`) → generate
  `attempt_id` + `fingerprint` → call `service.py` in-process → snapshot +
  hash → emit `tool_completed`/`tool_failed` → return result.
- Policy interface: `decide(pre_event, run_state) -> Allow | Block(feedback)
  | SubstituteResult(result)` — defined now so conditions A/B/C are just
  three implementations (PLAN §2).
- `runner/run.py` switches the agent from function tools to
  `MCPServerStreamableHttp` pointed at the facade (stdio fallback from
  Spike B if needed).

**Exit criteria:** Phase 2's ≥ 90% clean success reproduced *through the
facade*; every tool call appears in the trace with before/after hashes.

**Results:**
- Agent runs go through `MCPServerStreamableHttp` to a same-loop uvicorn
  facade. Domain calls stay in-process (`service.py`); fingerprints are
  minted at the facade. `create_appointment` hashes customer+slot, not
  `hold_id`. `AlwaysAllow` is the Phase 4 policy (condition A).
- `TraceHooks` records LLM/final-output only; tool events are facade-owned
  (`source=facade`) with before/after hashes. The 15-call cap still counts
  blocked calls and aborts via an MCP protocol error so the agent cannot
  keep requesting tools after the cap.
- Unit tests: 47 passed (`tests/test_facade.py` plus updated scripted
  traces through HTTP).
- Live: **10/10** clean runs through the facade (5 reschedule + 5 booking)
  on `deepseek-v4-flash`. Typical tool counts: 7–8 for reschedule, 5–6 for
  booking. Every tool event in a sampled live trace has `source=facade`
  and before/after hashes.
- Independent review (GPT-5.6 Sol), all findings addressed:
  - `build_agent()` requires `mcp_servers` (no direct-tool bypass).
  - `run_task` finishes the trace on failure, including KeyboardInterrupt
    (re-raised after `run_completed` / `finish_run`).
  - Recoverable handler errors and future faults return `{ok: false}`
    tool payloads so the agent can retry; only the call cap raises an
    MCP protocol error to hard-stop the run.
  - Uvicorn shutdown sets `force_exit` and drains pending HTTP closes.

---

## Phase 5 — Fault injection (Week 6)

**Goal:** deterministic failures on demand.

**Build:**

- `loopmedic/facade/faults.py` — injector keyed by scenario config
  `{fault_type, target_tool, trigger_on_call, seed}`:
  - `pre_execution_timeout` — don't call service; return timeout error
  - `post_commit_response_loss` — call service (write commits, ledger row
    SUCCEEDED); discard result; return the **same timeout error text** as
    pre-execution (indistinguishable to the agent, PLAN §3.4 fairness)
  - `stale_read` — return the previous snapshot's answer for that read
  - `transient_error` — fail call N, succeed on the next
- `scenarios/` — YAML format: task spec + fault spec + seed. Author 4
  smoke-test scenarios (one per fault).
- `tests/test_faults.py` — **scripted, no LLM:** after
  `post_commit_response_loss` on `create_appointment`, a scripted identical
  retry creates a second appointment (the Demo-2 proof); each fault
  reproduces byte-identically from its seed.

**Exit criteria:** all fault tests pass; a real-agent run under
`post_commit_response_loss` shows the timeout in its trace with the ledger
row marked SUCCEEDED.

**Results:**
- Injector (`loopmedic/facade/faults.py`) is keyed by
  `{fault_type, target_tool, trigger_on_call, seed}` and runs *after* the
  intervention policy. Pre-execution skips `service.py`; post-commit
  executes then replaces the result. Both timeouts use the same
  `{ok: false, code: timeout, error: "tool call timed out"}` payload
  (PLAN §3.4 fairness). `injected_fault` is stored on the trace event
  only — not in the agent-visible result.
- Stale reads return the last live answer for that exact tool+args (so a
  list after a create can still look empty, including the original `step`).
  There is no snapshot reconstruction: DomainSnapshot rows omit live fields
  such as `step`, and `trigger_on_call=1` would not be stale. A cache miss
  at the trigger raises instead of fabricating data. Transient errors fail
  call N and succeed on N+1 with a distinct `transient_error` code.
- `FaultSpec` rejects unknown tools, `stale_read` on writes,
  `post_commit_response_loss` on reads, `stale_read` with
  `trigger_on_call < 2`, and triggers past the 15-call cap. `seed` is
  required (experiment-matching key; these four faults are not randomized
  by it) and is recorded on `run_started`. One injector is bound to one
  `run_id`.
- Four smoke YAMLs in `scenarios/`. `run.py --scenario` loads them.
- Unit/scripted tests: **65 passed**. Scripted Demo-2 proof asserts
  timeline order: first `create_appointment` commits then returns timeout,
  identical retry succeeds; two CONFIRMED rows and two SUCCEEDED ledger
  fingerprints. All four faults reproduce with canonical JSON payloads and
  matching state hashes across two runs of the same spec.
- Live: run `c2956bef20b5` (`deepseek-v4-flash`, booking) under
  `smoke-post-commit-loss.yaml`. Trace shows `tool_failed` /
  `post_commit_response_loss` / timeout; ledger has SUCCEEDED `A004` then
  a retry `A005`. Condition A duplicated, as expected without LoopMedic.

---

## Phase 6 — Detectors (Week 7)

**Goal:** LoopMedic can see trouble; it cannot yet act.

**Build:**

- `loopmedic/core/detectors/` — one module each, all pure functions over the
  run's rolling feature state (testable with synthetic traces, no LLM):
  - `repetition.py` — canonical tool signature (tool + canonicalized args)
    repeat count
  - `error_streak.py` — normalized error (volatile fields stripped) repeated
    with no state-hash or argument change
  - `stagnation.py` — steps since last state-hash change
  - `unknown_commit.py` — two triggers (PLAN §6.4): observed timeout on a
    write whose ledger row is SUCCEEDED (proactive); proposed write matching
    a SUCCEEDED fingerprint (reactive)
  - `budget.py` — fraction of the 15-call cap consumed
- `loopmedic/core/features.py` — rolling per-run feature state updated on
  every event.
- Every detector emission stored in `detector_outputs` with its evidence
  (the specific events/hashes that triggered it).
- Premature-completion detection: harness-side check wired via the final
  output hook — evaluate required invariants at `final_output_proposed`.

**Exit criteria:** unit tests drive each detector with synthetic event
sequences (fire and no-fire cases); a real faulted run shows unknown-commit
evidence in its trace. No interventions yet — detectors observe only.

---

## Phase 7 — Recovery controller (Weeks 8–9)

**Goal:** detection becomes action, bounded and prioritized.

**Build:**

- `loopmedic/core/recovery.py` — the LoopMedic policy implementing the
  interface from Phase 4:
  - priority: hard rules (unknown-commit, premature-completion) > heuristics
    (≥ 2 corroborating signals, PLAN §3.12)
  - **verified-result substitution** (proactive): on observed write timeout
    with SUCCEEDED ledger row, return the verified outcome instead
  - **block duplicate write** (reactive): matching SUCCEEDED fingerprint ⇒
    Block with the verified ledger answer in the feedback
  - **safe retry**: ledger says the write never executed ⇒ retry once
  - **soft feedback**: wrap results on 2-signal repetition/stagnation
  - recovery budget = 2, then stop intervening; cooldown 2 steps; hard-stop
    only per PLAN §3.13
- `loopmedic/runner/recovery_packet.py` — structured continuation message
  for rejected completions: verified state, unmet invariants, blocked
  actions, remaining budget. Uses the Spike-A mechanism.
- Condition B policy (`RetryOnce`) implemented alongside — it's ~20 lines
  against the same interface.
- `tests/test_recovery.py` — scripted flows: lost response → substitution →
  no duplicate; substitution disabled → agent-style retry → block fires;
  scripted false-"done" → rejected → continuation happens (Demo 2/3/4
  proofs, no LLM).

**Exit criteria:** all scripted recovery tests pass; one real-model run of
each demo flow reproduced and its trace saved (these become the demo replays).

---

## Phase 8 — Scenarios and experiments (Week 10)

**Goal:** the 120-run matrix, reproducible from config.

**Build:**

- Author the full `scenarios/` set: 12 faulted (3 per fault type across
  booking/reschedule/cancel) + 8 clean controls.
- `loopmedic/evaluation/metrics.py` — per PLAN §7: success, safety-violation
  rate (history invariants), recovery rate, clean intervention rate, clean
  success delta, duplicates prevented, agent-requested vs
  environment-forwarded calls, tokens.
- `experiments/run_matrix.py` — reads one YAML (scenarios × {A,B,C} × 2
  reps), runs sequentially with fresh DB copies, writes results + metrics
  tables (CSV/JSON) into `experiments/results/<experiment_id>/`.

**Exit criteria:** the full matrix completes end-to-end; re-running the
metrics stage from stored traces reproduces identical tables; results
sanity-checked (C prevents duplicates B creates; clean success delta small).

---

## Phase 9 — Dashboard and tuning (Week 11) — last, after the matrix

**Goal:** every intervention explainable at a glance; clean runs unharmed.
Do not start this phase until Phases 1–8 (including the 120-run matrix)
are done. Core logic has no UI dependency.

**Build:**

- Custom dashboard (not Streamlit-first): run list with filters
  (condition, fault, verdict); per-run timeline (events, detector firings,
  interventions); state-diff view between any two snapshots; intervention
  panel showing the stored evidence; metrics summary table. Reads the JSON
  traces already written by Phase 8.
- Threshold tuning pass using clean-run traces: adjust stagnation N and
  repetition thresholds until clean intervention rate is near zero without
  losing faulted-run recoveries. Re-run affected matrix cells.

**Exit criteria:** clean success delta ≈ 0; every intervention in the final
matrix has a human-readable evidence trail in the dashboard; dashboard walks
through all five demo steps without touching a terminal.

---

## Phase 10 — Report and demo (Week 12)

**Build:** report (problem, design, implementation, experiment setup,
results, limitations, future work — the cut list in PLAN §1 is the future-work
section); demo rehearsal against the script in PLAN §10 with recorded replays
as backup for Demos 3 and 4; README with setup + how to add a
tool/fault/detector.

**Exit criteria:** demo runs in under 8 minutes twice in a row; report done.

---

## Standing rules

- Phases are gated by exit criteria, not dates. If a phase slips, cut
  scenarios (20 → 12) — never Phases 8–10.
- Anything that must be true for a demo gets a scripted, LLM-free test first.
- Never edit frozen design decisions in PLAN.md from inside a phase; if
  implementation contradicts the plan, stop and resolve explicitly.
