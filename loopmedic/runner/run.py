from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from agents import MaxTurnsExceeded, Model, RunConfig, Runner, ToolExecutionConfig
from agents.mcp import MCPServerStreamableHttp

from loopmedic.core.detectors import attach_detectors
from loopmedic.core.state_hash import hash_snapshot, snapshot_world
from loopmedic.core.trace_store import TraceStore
from loopmedic.environment.seed import write_pristine_db
from loopmedic.environment.service import connect, current_step
from loopmedic.evaluation.history import HistoryResult, evaluate_history
from loopmedic.evaluation.invariants import EvaluationResult, evaluate
from loopmedic.evaluation.scenario import load_scenario
from loopmedic.evaluation.tasks import TaskSpec, booking_task, reschedule_task
from loopmedic.facade.faults import FaultInjector, FaultSpec
from loopmedic.facade.policy import AlwaysAllow, InterventionPolicy
from loopmedic.facade.server import make_facade_server, serve_facade
from loopmedic.runner.agent import BookingContext, build_agent
from loopmedic.runner.config import (
    PROJECT_ROOT,
    TOOL_CALL_CAP,
    ToolBudgetExceeded,
    model_name,
)
from loopmedic.runner.hooks import TraceHooks

RUNS_DIR = PROJECT_ROOT / "runs"


@dataclass
class RunRecord:
    run_id: str
    task: TaskSpec
    passed: bool
    checks: dict[str, bool]
    history_checks: dict[str, bool] = field(default_factory=dict)
    tool_calls: int = 0
    final_output: str = ""
    error: str | None = None
    trace_path: str | None = None


def _unwrap_message(exc: BaseException) -> str:
    current: BaseException | None = exc
    for _ in range(6):
        if current is None:
            break
        if isinstance(current, ToolBudgetExceeded):
            return str(current)
        current = current.__cause__ or current.__context__
    return f"{type(exc).__name__}: {exc}"


async def _run_through_facade(
    *,
    task: TaskSpec,
    context: BookingContext,
    store: TraceStore,
    hooks: TraceHooks,
    model: Model | None,
    cap: int,
    policy: InterventionPolicy,
    injector: FaultInjector | None,
) -> str:
    server = make_facade_server(context, store, policy, injector)
    async with serve_facade(server) as url:
        async with MCPServerStreamableHttp(
            name="loopmedic-facade",
            params={"url": url},
            cache_tools_list=True,
            use_structured_content=True,
            failure_error_function=None,
        ) as mcp_client:
            result = await Runner.run(
                build_agent(model=model, mcp_servers=[mcp_client]),
                task.goal_text,
                context=context,
                max_turns=cap + 1,
                hooks=hooks,
                run_config=RunConfig(
                    tool_execution=ToolExecutionConfig(
                        max_function_tool_concurrency=1,
                    ),
                ),
            )
            output = str(result.final_output)
        await asyncio.sleep(0)
        return output


def run_task(
    task: TaskSpec,
    *,
    runs_dir: Path = RUNS_DIR,
    model: Model | None = None,
    cap: int = TOOL_CALL_CAP,
    policy: InterventionPolicy | None = None,
    fault: FaultSpec | None = None,
) -> RunRecord:
    run_id = uuid.uuid4().hex[:12]
    runs_dir.mkdir(parents=True, exist_ok=True)
    db_path = runs_dir / f"{run_id}.db"
    trace_path = runs_dir / f"{run_id}.trace.db"
    if fault is not None and fault.trigger_on_call > cap:
        raise ValueError(
            f"trigger_on_call {fault.trigger_on_call} exceeds tool cap {cap}"
        )
    write_pristine_db(db_path, seed=task.scenario_seed)
    conn = connect(db_path)
    store = TraceStore(trace_path)
    attach_detectors(store, conn, task=task, cap=cap)
    context = BookingContext(conn=conn, run_id=run_id, cap=cap)
    hooks = TraceHooks(store, record_tools=False)
    error: str | None = None
    final_output = ""
    verdict = EvaluationResult(passed=False, checks={})
    history = HistoryResult(passed=False, checks={})
    passed = False
    fatal: BaseException | None = None
    try:
        store.start_run(run_id, task, model_name() if model is None else "scripted")
        _emit_run_started(store, conn, run_id, fault)
        try:
            final_output = asyncio.run(
                _run_through_facade(
                    task=task,
                    context=context,
                    store=store,
                    hooks=hooks,
                    model=model,
                    cap=cap,
                    policy=policy or AlwaysAllow(),
                    injector=FaultInjector(fault) if fault is not None else None,
                )
            )
        except ToolBudgetExceeded as exc:
            error = str(exc)
            hooks.fail_open_calls(context, error)
        except MaxTurnsExceeded as exc:
            error = str(exc)
            hooks.fail_open_calls(context, error)
        except Exception as exc:
            error = _unwrap_message(exc)
            hooks.fail_open_calls(context, error)
        except BaseException as exc:
            error = _unwrap_message(exc)
            hooks.fail_open_calls(context, error)
            fatal = exc
        if context.tool_calls > cap:
            error = str(ToolBudgetExceeded(cap))
        try:
            verdict = evaluate(conn, task)
            history = evaluate_history(
                store.list_snapshots(run_id),
                task,
            )
        except Exception as exc:
            if error is None:
                error = f"{type(exc).__name__}: {exc}"
            verdict = EvaluationResult(passed=False, checks={})
            history = HistoryResult(passed=False, checks={})
        passed = verdict.passed and history.passed and error is None
        store.emit(
            run_id,
            "run_completed",
            step_index=current_step(conn),
            error=error,
            result={"passed": passed, "output": final_output},
        )
        store.finish_run(run_id, passed=passed, error=error)
    except BaseException as exc:
        try:
            store.finish_run(
                run_id,
                passed=False,
                error=error or _unwrap_message(exc),
            )
        except Exception:
            pass
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            fatal = exc
        elif fatal is None:
            raise
    finally:
        store.close()
        conn.close()
    if fatal is not None:
        raise fatal
    return RunRecord(
        run_id=run_id,
        task=task,
        passed=passed,
        checks=verdict.checks,
        history_checks=history.checks,
        tool_calls=context.tool_calls,
        final_output=final_output,
        error=error,
        trace_path=str(trace_path),
    )


def _emit_run_started(
    store: TraceStore,
    conn,
    run_id: str,
    fault: FaultSpec | None = None,
) -> None:
    snapshot = snapshot_world(conn)
    digest = hash_snapshot(snapshot)
    store.emit(
        run_id,
        "run_started",
        step_index=current_step(conn),
        state_hash_after=digest,
        snapshot=snapshot,
        snapshot_hash=digest,
        result={"fault": fault.model_dump() if fault is not None else None},
    )


def _print_record(record: RunRecord) -> None:
    status = "PASS" if record.passed else "FAIL"
    print(
        f"{status} run={record.run_id} model={model_name()} "
        f"tools={record.tool_calls} customer={record.task.customer_id}"
    )
    for name, ok in record.checks.items():
        print(f"  {name}: {ok}")
    for name, ok in record.history_checks.items():
        print(f"  history.{name}: {ok}")
    if record.error:
        print(f"  error: {record.error}")
    if record.final_output:
        print(f"  output: {record.final_output[:500]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LoopMedic baseline agent.")
    parser.add_argument(
        "--task",
        choices=("reschedule", "booking", "baseline"),
        default="reschedule",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=None,
        help="YAML scenario with optional fault spec (Phase 5+).",
    )
    args = parser.parse_args()
    if args.scenario is not None:
        loaded = load_scenario(args.scenario)
        record = run_task(loaded.task, fault=loaded.fault)
        _print_record(record)
        return
    if args.task == "baseline":
        tasks = ([reschedule_task()] * 5) + ([booking_task()] * 5)
    elif args.task == "booking":
        tasks = [booking_task()] * args.repeat
    else:
        tasks = [reschedule_task()] * args.repeat
    records = [run_task(task) for task in tasks]
    for record in records:
        _print_record(record)
    passed = sum(1 for record in records if record.passed)
    print(f"{passed}/{len(records)} passed")
    if passed / len(records) < 0.9:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
