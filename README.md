# LoopMedic

Runtime supervisor for a tool-using LLM agent on a fictional appliance-service
booking system. The agent talks MCP to a facade that records every call,
injects deterministic faults, and (from Phase 7) applies recovery. Scoring is
SQLite invariants, not an LLM judge.

Implemented through Phase 5 (environment, tracing, facade, faults). Frozen
design: `PLAN.md`. Phase status: `PHASES.md`.

## Setup

Python 3.12+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Live runs need `OPENCODE_API_KEY` in `.env` (OpenCode Go). Optional:
`LOOPMEDIC_MODEL` (default `deepseek-v4-flash`).

## Tests

```bash
pytest
```

## Run

```bash
python -m loopmedic.runner.run --task booking
python -m loopmedic.runner.run --task baseline
python -m loopmedic.runner.run --scenario scenarios/smoke-post-commit-loss.yaml
```

World DBs and traces go in `runs/` (gitignored).
