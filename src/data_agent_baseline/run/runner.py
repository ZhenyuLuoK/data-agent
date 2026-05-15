from __future__ import annotations

import csv
import json
import logging
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from data_agent_baseline.agents.langgraph_agent import (
    LangGraphAgent,
    LangGraphAgentConfig,
    build_chat_openai,
)
from data_agent_baseline.agents.model import OpenAIModelAdapter
from data_agent_baseline.agents.react import ReActAgent, ReActAgentConfig
from data_agent_baseline.benchmark.dataset import DABenchPublicDataset
from data_agent_baseline.config import AppConfig
from data_agent_baseline.logging_setup import bind_task_log_file
from data_agent_baseline.run.vote import (
    discover_candidate_filenames,
    vote_all_tasks,
    vote_task_with_candidates,
)
from data_agent_baseline.tools.registry import ToolRegistry, create_default_tool_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaskRunArtifacts:
    task_id: str
    task_output_dir: Path
    prediction_csv_path: Path | None
    trace_path: Path
    succeeded: bool
    failure_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_output_dir": str(self.task_output_dir),
            "prediction_csv_path": str(self.prediction_csv_path) if self.prediction_csv_path else None,
            "trace_path": str(self.trace_path),
            "succeeded": self.succeeded,
            "failure_reason": self.failure_reason,
        }


def create_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def resolve_run_id(run_id: str | None = None) -> str:
    if run_id is None:
        return create_run_id()

    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must not be empty.")
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError("run_id must be a single directory name, not a path.")
    return normalized


def create_run_output_dir(output_root: Path, *, run_id: str | None = None) -> tuple[str, Path]:
    effective_run_id = resolve_run_id(run_id)
    run_output_dir = output_root / effective_run_id
    run_output_dir.mkdir(parents=True, exist_ok=False)
    return effective_run_id, run_output_dir


def build_model_adapter(config: AppConfig):
    """Build the LLM client used by the LangGraph agent.

    Kept under the legacy name so external callers/tests that wired in a
    pre-built model via ``run_single_task(model=...)`` keep working — they
    just need to pass a ``ChatOpenAI``-compatible object instead of the old
    ``OpenAIModelAdapter``.
    """

    return build_chat_openai(
        model=config.agent.model,
        api_base=config.agent.api_base,
        api_key=config.agent.api_key,
        temperature=config.agent.temperature,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_csv(path: Path, columns: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)


def _failure_run_result_payload(task_id: str, failure_reason: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "answer": None,
        "steps": [],
        "failure_reason": failure_reason,
        "succeeded": False,
    }


def _run_single_task_core(
    *,
    task_id: str,
    config: AppConfig,
    model=None,
    tools: ToolRegistry | None = None,
    task_output_dir: Path | None = None,
) -> dict[str, Any]:
    public_dataset = DABenchPublicDataset(config.dataset.root_path)
    task = public_dataset.get_task(task_id)

    if config.agent.agent_type == "react":
        # Legacy pure-ReAct agent: uses OpenAIModelAdapter + ToolRegistry.
        react_model = OpenAIModelAdapter(
            model=config.agent.model,
            api_base=config.agent.api_base,
            api_key=config.agent.api_key,
            temperature=config.agent.temperature,
        )
        react_tools = tools or create_default_tool_registry()
        react_agent = ReActAgent(
            model=react_model,
            tools=react_tools,
            config=ReActAgentConfig(max_steps=config.agent.max_steps),
        )
        run_result = react_agent.run(task)
        return run_result.to_dict()

    # Default: LangGraph DAG-based agent.
    # ``tools`` is preserved in the signature for backward compatibility with
    # the legacy ReAct ToolRegistry callers. The LangGraph agent builds its
    # own per-task LangChain tool list internally, so the argument is unused
    # here and intentionally discarded.
    del tools

    agent = LangGraphAgent(
        model=model or build_model_adapter(config),
        config=LangGraphAgentConfig(),
    )
    run_result = agent.run(task, task_output_dir=task_output_dir)
    return run_result.to_dict()

def _run_single_task_in_subprocess(
    task_id: str,
    config: AppConfig,
    queue: multiprocessing.Queue[Any],
    task_output_dir: Path | None = None,
) -> None:
    try:
        queue.put(
            {
                "ok": True,
                "run_result": _run_single_task_core(
                    task_id=task_id,
                    config=config,
                    task_output_dir=task_output_dir,
                ),
            }
        )
    except BaseException as exc:  # noqa: BLE001
        queue.put(
            {
                "ok": False,
                "error": str(exc),
            }
        )

def _run_single_task_with_timeout(
    *,
    task_id: str,
    config: AppConfig,
    task_output_dir: Path | None = None,
) -> dict[str, Any]:
    timeout_seconds = config.run.task_timeout_seconds
    if timeout_seconds <= 0:
        return _run_single_task_core(
            task_id=task_id, config=config, task_output_dir=task_output_dir
        )

    queue: multiprocessing.Queue[Any] = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_run_single_task_in_subprocess,
        args=(task_id, config, queue, task_output_dir),
    )
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join()
        return _failure_run_result_payload(task_id, f"Task timed out after {timeout_seconds} seconds.")

    if queue.empty():
        exit_code = process.exitcode
        if exit_code not in (None, 0):
            return _failure_run_result_payload(
                task_id,
                f"Task exited unexpectedly with exit code {exit_code}.",
            )
        return _failure_run_result_payload(task_id, "Task exited without returning a result.")

    result = queue.get()
    if result.get("ok"):
        return dict(result["run_result"])
    return _failure_run_result_payload(task_id, f"Task failed with uncaught error: {result['error']}")


def _round_artifact_filename(round_idx: int, base_already_exists: bool) -> str:
    """Decide which filename a given round should write its prediction to.

    Semantics (generalised to support any ``vote_rounds`` value, including
    ``> 3`` where round 4+ feed the per-task incremental vote):
      * Round 1 → always "prediction.csv" (the baseline that the entrypoint
        sync loop will flatten to /output/task_*/ as soon as it lands).
      * Round N >= 2 with prediction.csv already on disk → "rN.csv" (an
        extra candidate that participates in voting but does NOT clobber
        the canonical file mid-run; voting decides whether to overwrite).
      * Round N >= 2 with no prediction.csv on disk → "prediction.csv" (a
        back-fill: every earlier round failed to produce anything for this
        task, so this round becomes the de-facto baseline).
    """
    if round_idx <= 1:
        return "prediction.csv"
    if base_already_exists:
        return f"r{round_idx}.csv"
    return "prediction.csv"


def _write_task_outputs(
    task_id: str,
    run_output_dir: Path,
    run_result: dict[str, Any],
    *,
    prediction_filename: str = "prediction.csv",
    trace_suffix: str = "",
) -> TaskRunArtifacts:
    task_output_dir = run_output_dir / task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)
    # trace files for rounds 2/3 carry a suffix so they don't overwrite
    # round 1's trace.json — useful for post-hoc debugging "did the agent
    # actually disagree across rounds, or just emit equivalent answers?".
    trace_filename = f"trace{trace_suffix}.json" if trace_suffix else "trace.json"
    trace_path = task_output_dir / trace_filename
    _write_json(trace_path, run_result)

    prediction_csv_path: Path | None = None
    answer = run_result.get("answer")
    if isinstance(answer, dict):
        prediction_csv_path = task_output_dir / prediction_filename
        _write_csv(
            prediction_csv_path,
            list(answer.get("columns", [])),
            [list(row) for row in answer.get("rows", [])],
        )

    return TaskRunArtifacts(
        task_id=task_id,
        task_output_dir=task_output_dir,
        prediction_csv_path=prediction_csv_path,
        trace_path=trace_path,
        succeeded=bool(run_result.get("succeeded")),
        failure_reason=run_result.get("failure_reason"),
    )


def run_single_task(
    *,
    task_id: str,
    config: AppConfig,
    run_output_dir: Path,
    model=None,
    tools: ToolRegistry | None = None,
    prediction_filename: str = "prediction.csv",
    trace_suffix: str = "",
) -> TaskRunArtifacts:
    started_at = perf_counter()
    # Pre-create the per-task output directory so the DAG visualizer
    # can drop dag.svg into it as the run progresses, instead of only
    # appearing after the whole trace.json is finalized.
    task_output_dir = run_output_dir / task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)

    # Bind a per-task FileHandler so every log record emitted while this
    # task runs is captured to <task_output_dir>/agent.log. The context
    # manager detaches the handler on exit so subsequent tasks (in the
    # same process — e.g. ``max_workers=1`` benchmarks) don't bleed logs
    # into earlier files.
    with bind_task_log_file(task_output_dir) as task_log_path:
        logger.info(
            "task_started task_id=%s prediction_filename=%s trace_suffix=%s log=%s",
            task_id,
            prediction_filename,
            trace_suffix or "(none)",
            task_log_path or "(disabled)",
        )

        try:
            if model is None and tools is None:
                run_result = _run_single_task_with_timeout(
                    task_id=task_id, config=config, task_output_dir=task_output_dir
                )
            else:
                run_result = _run_single_task_core(
                    task_id=task_id,
                    config=config,
                    model=model,
                    tools=tools,
                    task_output_dir=task_output_dir,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("task_crashed task_id=%s error=%s", task_id, exc)
            run_result = _failure_run_result_payload(
                task_id, f"Uncaught exception: {exc}"
            )
        run_result["e2e_elapsed_seconds"] = round(perf_counter() - started_at, 3)

        artifacts = _write_task_outputs(
            task_id,
            run_output_dir,
            run_result,
            prediction_filename=prediction_filename,
            trace_suffix=trace_suffix,
        )
        if artifacts.succeeded:
            logger.info(
                "task_finished_ok task_id=%s elapsed=%.3fs prediction=%s",
                task_id,
                run_result["e2e_elapsed_seconds"],
                artifacts.prediction_csv_path,
            )
        else:
            logger.warning(
                "task_finished_fail task_id=%s elapsed=%.3fs reason=%s",
                task_id,
                run_result["e2e_elapsed_seconds"],
                artifacts.failure_reason,
            )
        return artifacts


_INCREMENTAL_VOTE_ROUND_THRESHOLD = 4


def _maybe_incremental_vote(
    *,
    round_idx: int,
    artifact: TaskRunArtifacts,
    run_output_dir: Path,
) -> None:
    """Run a per-task incremental vote when ``round_idx`` is 4 or higher.

    When ``vote_rounds > 3``, every round at or beyond round 4 produces a
    fresh ``rN.csv`` per task. As soon as that file lands, we recompute the
    winner across ``prediction.csv`` (current best) plus every ``rK.csv``
    that already exists (K=2..round_idx), and atomically overwrite
    ``prediction.csv`` if a new winner emerges.

    Decision rule (matches the user-requested protocol):
      * Most-frequent normalised-table signature wins.
      * If every signature is distinct, fall back to the EARLIEST candidate
        (priority order is ``prediction.csv``, then ``r2.csv``, ``r3.csv``,
        …). I.e. "if all results differ, keep the first one".

    Failures here are deliberately swallowed: voting is a best-effort
    optimisation on top of the runner. A vote crash should never abort an
    in-progress benchmark — the canonical ``prediction.csv`` remains
    whatever the previous successful round left there.
    """

    if round_idx < _INCREMENTAL_VOTE_ROUND_THRESHOLD:
        return

    task_dir = artifact.task_output_dir
    candidates = discover_candidate_filenames(task_dir)
    # Need at least one rN.csv on disk for an incremental vote to be
    # meaningful — if the only candidate is ``prediction.csv`` the vote
    # is a no-op.
    if len(candidates) < 2:
        return
    try:
        vote_task_with_candidates(task_dir, candidates)
    except Exception:  # noqa: BLE001 — never let voting crash the run.
        # Swallow on purpose; the canonical prediction.csv is still whatever
        # an earlier round wrote. Future rounds will re-attempt voting.
        return


def _execute_one_round(
    *,
    round_idx: int,
    total_rounds: int,
    task_ids: list[str],
    run_output_dir: Path,
    config: AppConfig,
    effective_workers: int,
    shared_model: Any | None,
    shared_tools: ToolRegistry | None,
    progress_callback: Callable[[TaskRunArtifacts], None] | None,
) -> list[TaskRunArtifacts]:
    """Run all tasks once, applying round-aware filename selection.

    The "fill-in" semantics rely on a critical invariant: the decision of
    "does prediction.csv already exist?" is made AT SUBMIT TIME, not inside
    the worker. Otherwise N concurrent round-2 workers would all see "no
    prediction.csv" and all back-fill, racing to clobber the round-1
    fallback. Submitting in a single thread avoids that race entirely.

    When ``round_idx >= _INCREMENTAL_VOTE_ROUND_THRESHOLD`` (i.e. round 4
    onward when ``vote_rounds > 3``), each task's brand-new ``rN.csv``
    triggers an immediate per-task vote so ``prediction.csv`` always
    reflects the best answer the runner has seen so far. The end-of-run
    ``vote_all_tasks`` sweep still runs as a final reconciliation.
    """
    trace_suffix = "" if round_idx == 1 else f"_r{round_idx}"

    def _resolve_filename(task_id: str) -> str:
        base_path = run_output_dir / task_id / "prediction.csv"
        return _round_artifact_filename(round_idx, base_already_exists=base_path.exists())

    task_artifacts: list[TaskRunArtifacts]
    if effective_workers == 1:
        # Sequential path also computes the filename right before each task,
        # which is correct because the previous task has already finished
        # by the time we look at its prediction.csv.
        task_artifacts = []
        for task_id in task_ids:
            prediction_filename = _resolve_filename(task_id)
            artifact = run_single_task(
                task_id=task_id,
                config=config,
                run_output_dir=run_output_dir,
                model=shared_model,
                tools=shared_tools,
                prediction_filename=prediction_filename,
                trace_suffix=trace_suffix,
            )
            task_artifacts.append(artifact)
            _maybe_incremental_vote(
                round_idx=round_idx,
                artifact=artifact,
                run_output_dir=run_output_dir,
            )
            if progress_callback is not None:
                progress_callback(artifact)
    else:
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            # IMPORTANT: resolve the filename eagerly in the submit loop so
            # that all rounds-2/3 workers in the same pool agree on which
            # tasks need a back-fill vs an rN candidate.
            future_to_index: dict[Any, int] = {}
            for index, task_id in enumerate(task_ids):
                prediction_filename = _resolve_filename(task_id)
                future = executor.submit(
                    run_single_task,
                    task_id=task_id,
                    config=config,
                    run_output_dir=run_output_dir,
                    prediction_filename=prediction_filename,
                    trace_suffix=trace_suffix,
                )
                future_to_index[future] = index

            indexed_artifacts: list[TaskRunArtifacts | None] = [None] * len(task_ids)
            for future in as_completed(future_to_index):
                artifact = future.result()
                indexed_artifacts[future_to_index[future]] = artifact
                # Incremental vote runs in the as_completed loop (single
                # consumer thread), so it stays serialised for the same
                # task even when worker threads run round 4+ concurrently.
                # That's important: two parallel votes on the same task_dir
                # would race on the prediction.csv atomic overwrite.
                _maybe_incremental_vote(
                    round_idx=round_idx,
                    artifact=artifact,
                    run_output_dir=run_output_dir,
                )
                if progress_callback is not None:
                    progress_callback(artifact)
            task_artifacts = [a for a in indexed_artifacts if a is not None]

    # Lightweight per-round breadcrumb (helps diagnose "round 2 OOM'd halfway").
    del total_rounds  # currently unused; kept for future "round X/Y" log lines
    return task_artifacts


def run_benchmark(
    *,
    config: AppConfig,
    model=None,
    tools: ToolRegistry | None = None,
    limit: int | None = None,
    progress_callback: Callable[[TaskRunArtifacts], None] | None = None,
) -> tuple[Path, list[TaskRunArtifacts]]:
    effective_run_id, run_output_dir = create_run_output_dir(config.run.output_dir, run_id=config.run.run_id)

    dataset = DABenchPublicDataset(config.dataset.root_path)
    tasks = dataset.iter_tasks()
    if limit is not None:
        tasks = tasks[:limit]

    effective_workers = config.run.max_workers
    if effective_workers < 1:
        raise ValueError("max_workers must be at least 1.")
    # Same constraint as before: callers that hand-inject a model or tools
    # are using the in-process LangChain client and MUST stay single-threaded.
    if model is not None or tools is not None:
        effective_workers = 1

    task_ids = [task.task_id for task in tasks]

    vote_rounds = max(1, config.run.vote_rounds)
    shared_model = model
    shared_tools = tools
    if effective_workers == 1:
        # Build the shared LangChain model + tool registry exactly once,
        # since all rounds will reuse them.
        shared_model = shared_model or build_model_adapter(config)
        shared_tools = shared_tools or create_default_tool_registry()

    rounds_summary: list[dict[str, Any]] = []
    last_round_artifacts: list[TaskRunArtifacts] = []
    for round_idx in range(1, vote_rounds + 1):
        round_artifacts = _execute_one_round(
            round_idx=round_idx,
            total_rounds=vote_rounds,
            task_ids=task_ids,
            run_output_dir=run_output_dir,
            config=config,
            effective_workers=effective_workers,
            shared_model=shared_model,
            shared_tools=shared_tools,
            progress_callback=progress_callback,
        )
        rounds_summary.append(
            {
                "round": round_idx,
                "task_count": len(round_artifacts),
                "succeeded_task_count": sum(1 for a in round_artifacts if a.succeeded),
            }
        )
        last_round_artifacts = round_artifacts

    # ---- Retry pass: run every still-failed case once more --------------
    # After all vote rounds finish, scan the latest snapshot of each task and
    # re-run any case whose `succeeded` flag is still False (i.e. the agent
    # never produced an answer or surfaced a failure_reason). The retry runs
    # exactly once per failed case; its outputs are written to dedicated
    # `prediction_retry.csv` / `trace_retry.json` files first, and only
    # **promoted** to overwrite the canonical `prediction.csv` / `trace.json`
    # if the retry actually succeeds. A failed retry is discarded so the
    # original (failed) artifacts on disk are preserved untouched.
    retry_pass_summary: dict[str, Any] | None = None
    if last_round_artifacts:
        last_round_artifacts, retry_pass_summary = _execute_retry_pass(
            artifacts=last_round_artifacts,
            run_output_dir=run_output_dir,
            config=config,
            effective_workers=effective_workers,
            shared_model=shared_model,
            shared_tools=shared_tools,
        )

    vote_summary_payload: dict[str, Any] | None = None
    if vote_rounds >= 2:
        # Voting is local and O(N) CSV parsing — runs in milliseconds even
        # for a 50-task benchmark, so we don't bother gating it behind a
        # progress bar.
        vote_results = vote_all_tasks(run_output_dir)
        vote_summary_payload = {
            task_id: result.to_dict() for task_id, result in vote_results.items()
        }

    summary_path = run_output_dir / "summary.json"
    _write_json(
        summary_path,
        {
            "run_id": effective_run_id,
            # task_count / succeeded_task_count reflect the LAST round, which
            # mirrors the legacy single-round semantics for callers that
            # still inspect these top-level fields.
            "task_count": len(last_round_artifacts),
            "succeeded_task_count": sum(1 for a in last_round_artifacts if a.succeeded),
            "max_workers": effective_workers,
            "vote_rounds": vote_rounds,
            "rounds": rounds_summary,
            "retry_pass": retry_pass_summary,
            "vote_summary": vote_summary_payload,
            "tasks": [a.to_dict() for a in last_round_artifacts],
        },
    )
    return run_output_dir, last_round_artifacts


# ---------------------------------------------------------------------------
# Retry pass helpers
# ---------------------------------------------------------------------------

# Filenames used by the retry pass. We deliberately write to dedicated names
# first so a *failed* retry never clobbers the original (failed) artifacts —
# only a successful retry gets promoted to the canonical filenames.
_RETRY_PREDICTION_FILENAME = "prediction_retry.csv"
_RETRY_TRACE_SUFFIX = "_retry"
_RETRY_TRACE_FILENAME = f"trace{_RETRY_TRACE_SUFFIX}.json"


def _promote_retry_artifacts(retry_artifact: TaskRunArtifacts) -> TaskRunArtifacts:
    """Promote a successful retry's outputs to the canonical filenames.

    Overwrites `prediction.csv` with `prediction_retry.csv` and `trace.json`
    with `trace_retry.json`, then removes the retry-only files. Returns a
    new ``TaskRunArtifacts`` whose paths point at the canonical files so
    downstream summary / vote logic sees a consistent view.
    """
    task_output_dir = retry_artifact.task_output_dir
    canonical_trace = task_output_dir / "trace.json"
    canonical_prediction = task_output_dir / "prediction.csv"

    retry_trace = task_output_dir / _RETRY_TRACE_FILENAME
    if retry_trace.exists():
        # Path.replace is atomic on POSIX and overwrites the destination.
        retry_trace.replace(canonical_trace)

    promoted_prediction_path: Path | None = None
    retry_prediction = retry_artifact.prediction_csv_path
    if retry_prediction is not None and retry_prediction.exists():
        retry_prediction.replace(canonical_prediction)
        promoted_prediction_path = canonical_prediction

    return TaskRunArtifacts(
        task_id=retry_artifact.task_id,
        task_output_dir=task_output_dir,
        prediction_csv_path=promoted_prediction_path,
        trace_path=canonical_trace,
        succeeded=retry_artifact.succeeded,
        failure_reason=retry_artifact.failure_reason,
    )


def _discard_retry_artifacts(task_output_dir: Path) -> None:
    """Remove leftover retry-only files for a *failed* retry.

    Keeps the original `prediction.csv` / `trace.json` (which reflect the
    pre-retry failure) intact so downstream tooling sees the canonical
    failure state, not a half-written retry.
    """
    for filename in (_RETRY_PREDICTION_FILENAME, _RETRY_TRACE_FILENAME):
        stale = task_output_dir / filename
        if stale.exists():
            stale.unlink()


def _execute_retry_pass(
    *,
    artifacts: list[TaskRunArtifacts],
    run_output_dir: Path,
    config: AppConfig,
    effective_workers: int,
    shared_model: Any | None,
    shared_tools: ToolRegistry | None,
) -> tuple[list[TaskRunArtifacts], dict[str, Any] | None]:
    """Re-run every still-failed task exactly once.

    Returns ``(updated_artifacts, summary)``. ``updated_artifacts`` preserves
    the original task ordering; entries for tasks whose retry succeeded are
    swapped in-place. ``summary`` is ``None`` when no task needed retrying.
    """
    failed_indices = [i for i, a in enumerate(artifacts) if not a.succeeded]
    if not failed_indices:
        return artifacts, None

    failed_task_ids = [artifacts[i].task_id for i in failed_indices]

    def _run_retry(task_id: str) -> TaskRunArtifacts:
        return run_single_task(
            task_id=task_id,
            config=config,
            run_output_dir=run_output_dir,
            model=shared_model,
            tools=shared_tools,
            prediction_filename=_RETRY_PREDICTION_FILENAME,
            trace_suffix=_RETRY_TRACE_SUFFIX,
        )

    retry_artifacts: dict[str, TaskRunArtifacts] = {}
    if effective_workers == 1:
        for task_id in failed_task_ids:
            retry_artifacts[task_id] = _run_retry(task_id)
    else:
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            future_to_task_id = {
                executor.submit(_run_retry, task_id): task_id
                for task_id in failed_task_ids
            }
            for future in as_completed(future_to_task_id):
                task_id = future_to_task_id[future]
                retry_artifacts[task_id] = future.result()

    # Promote successful retries to the canonical filenames; discard the rest.
    updated_artifacts = list(artifacts)
    promoted_count = 0
    for index in failed_indices:
        original = artifacts[index]
        retry_artifact = retry_artifacts[original.task_id]
        if retry_artifact.succeeded:
            updated_artifacts[index] = _promote_retry_artifacts(retry_artifact)
            promoted_count += 1
        else:
            _discard_retry_artifacts(retry_artifact.task_output_dir)
            # Keep the original failed artifact in place; the retry's own
            # failure_reason is intentionally dropped per the "failed retry
            # leaves no trace" contract.

    summary = {
        "retried_task_count": len(failed_task_ids),
        "promoted_task_count": promoted_count,
        "still_failed_task_count": len(failed_task_ids) - promoted_count,
        "retried_task_ids": failed_task_ids,
    }
    return updated_artifacts, summary
