from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from data_agent_baseline.benchmark.dataset import DABenchPublicDataset
from data_agent_baseline.config import load_app_config

# NOTE: ``data_agent_baseline.run.runner`` pulls in the heavy LangGraph + agent
# stack (langgraph_agent → matplotlib via dag_visualizer). To keep light-weight
# subcommands like ``score`` usable in environments that don't have the agent
# extras installed, we import runner lazily inside the run-* subcommands.
from data_agent_baseline.run.scoring import (
    DEFAULT_LAMBDA,
    RunScore,
    score_run,
    write_score_report,
)
from data_agent_baseline.tools.filesystem import list_context_tree

if TYPE_CHECKING:  # only needed for static typing of the helper signatures
    from data_agent_baseline.run.runner import TaskRunArtifacts

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS_DIR = PROJECT_ROOT / "configs"
DATA_DIR = PROJECT_ROOT / "data"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ARTIFACT_RUNS_DIR = ARTIFACTS_DIR / "runs"

app = typer.Typer(add_completion=False, no_args_is_help=False)
console = Console()


def _status_value(path: Path) -> str:
    return "present" if path.exists() else "missing"


def _format_compact_rate(completed_count: int, elapsed_seconds: float) -> str:
    if completed_count <= 0 or elapsed_seconds <= 0:
        return "rate=0.0 task/min"
    return f"rate={(completed_count / elapsed_seconds) * 60:.1f} task/min"


def _format_last_task(artifact: "TaskRunArtifacts | None") -> str:
    if artifact is None:
        return "last=-"
    status = "ok" if artifact.succeeded else "fail"
    return f"last={artifact.task_id} ({status})"


def _build_compact_progress_fields(
    *,
    completed_count: int,
    succeeded_count: int,
    failed_count: int,
    task_total: int,
    max_workers: int,
    elapsed_seconds: float,
    last_artifact: "TaskRunArtifacts | None",
) -> dict[str, str]:
    remaining_count = max(task_total - completed_count, 0)
    running_count = min(max_workers, remaining_count)
    queued_count = max(remaining_count - running_count, 0)
    return {
        "ok": str(succeeded_count),
        "fail": str(failed_count),
        "run": str(running_count),
        "queue": str(queued_count),
        "speed": _format_compact_rate(completed_count, elapsed_seconds),
        "last": _format_last_task(last_artifact),
    }


@app.callback()
def cli() -> None:
    """Utilities for working with the local DABench baseline project."""


@app.command()
def status(
    config: Path = typer.Option(..., exists=True, dir_okay=False, help="YAML config path."),
) -> None:
    """Show the local project layout and public dataset presence."""
    app_config = load_app_config(config)
    config_path = config.resolve()
    public_dataset = DABenchPublicDataset(app_config.dataset.root_path)

    table = Table(title="DABench Baseline Status")
    table.add_column("Item")
    table.add_column("Path")
    table.add_column("State")

    table.add_row("project_root", str(PROJECT_ROOT), "ready")
    table.add_row("data_dir", str(DATA_DIR), _status_value(DATA_DIR))
    table.add_row("configs_dir", str(CONFIGS_DIR), _status_value(CONFIGS_DIR))
    table.add_row("artifacts_dir", str(ARTIFACTS_DIR), _status_value(ARTIFACTS_DIR))
    table.add_row("runs_dir", str(ARTIFACT_RUNS_DIR), _status_value(ARTIFACT_RUNS_DIR))
    table.add_row("dataset_root", str(app_config.dataset.root_path), _status_value(app_config.dataset.root_path))
    table.add_row("config_path", str(config_path), _status_value(config_path))

    console.print(table)

    if public_dataset.exists:
        console.print(f"Public tasks: {len(public_dataset.list_task_ids())}")
        counts = public_dataset.task_counts()
        if counts:
            rendered_counts = ", ".join(
                f"{difficulty}={count}" for difficulty, count in sorted(counts.items())
            )
            console.print(f"Public task counts: {rendered_counts}")


@app.command("inspect-task")
def inspect_task(
    task_id: str,
    config: Path = typer.Option(..., exists=True, dir_okay=False, help="YAML config path."),
) -> None:
    """Show task metadata and available context files."""
    app_config = load_app_config(config)
    dataset = DABenchPublicDataset(app_config.dataset.root_path)
    task = dataset.get_task(task_id)
    console.print(f"Task: {task.task_id}")
    console.print(f"Difficulty: {task.difficulty}")
    console.print(f"Question: {task.question}")
    context_listing = list_context_tree(task)
    table = Table(title=f"Context Files for {task.task_id}")
    table.add_column("Path")
    table.add_column("Kind")
    table.add_column("Size")
    for entry in context_listing["entries"]:
        table.add_row(str(entry["path"]), str(entry["kind"]), str(entry["size"] or ""))
    console.print(table)


@app.command("run-task")
def run_task_command(
    task_id: str,
    config: Path = typer.Option(..., exists=True, dir_okay=False, help="YAML config path."),
) -> None:
    """Run the ReAct baseline on one task."""
    # Lazy import to keep `score` / `status` / `inspect-task` usable when the
    # heavy LangGraph stack is unavailable.
    from data_agent_baseline.run.runner import create_run_output_dir, run_single_task

    app_config = load_app_config(config)
    try:
        _, run_output_dir = create_run_output_dir(app_config.run.output_dir, run_id=app_config.run.run_id)
    except (ValueError, FileExistsError) as exc:
        raise typer.BadParameter(str(exc), param_hint="run.run_id") from exc
    artifacts = run_single_task(task_id=task_id, config=app_config, run_output_dir=run_output_dir)

    console.print(f"Run output: {run_output_dir}")
    console.print(f"Task output: {artifacts.task_output_dir}")
    if artifacts.prediction_csv_path is not None:
        console.print(f"Prediction CSV: {artifacts.prediction_csv_path}")
    else:
        console.print("Prediction CSV: not generated")
    if artifacts.failure_reason is not None:
        console.print(f"Failure: {artifacts.failure_reason}")


@app.command("run-benchmark")
def run_benchmark_command(
    config: Path = typer.Option(..., exists=True, dir_okay=False, help="YAML config path."),
    limit: int | None = typer.Option(None, min=1, help="Maximum number of tasks to run."),
) -> None:
    """Run the ReAct baseline on multiple tasks from the config selection."""
    # Lazy import (see note at top of file).
    from data_agent_baseline.run.runner import run_benchmark

    app_config = load_app_config(config)
    dataset = DABenchPublicDataset(app_config.dataset.root_path)
    task_count_per_round = len(dataset.iter_tasks())
    if limit is not None:
        task_count_per_round = min(task_count_per_round, limit)
    # 三轮投票时进度条总量按 (task_count × vote_rounds) 计：runner 每跑完一个
    # (task, round) 都会回调一次 on_task_complete，进度条才能在多轮间平滑前进。
    vote_rounds = max(1, app_config.run.vote_rounds)
    task_total = task_count_per_round * vote_rounds
    effective_workers = app_config.run.max_workers

    progress_columns = [
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[dim]|[/dim]"),
        TextColumn("[green]ok={task.fields[ok]}[/green]"),
        TextColumn("[red]fail={task.fields[fail]}[/red]"),
        TextColumn("[cyan]run={task.fields[run]}[/cyan]"),
        TextColumn("[yellow]queue={task.fields[queue]}[/yellow]"),
        TextColumn("[dim]|[/dim]"),
        TextColumn("{task.fields[speed]}"),
        TextColumn("[dim]| elapsed[/dim]"),
        TimeElapsedColumn(),
        TextColumn("[dim]| eta[/dim]"),
        TimeRemainingColumn(),
        TextColumn("[dim]|[/dim]"),
        TextColumn("{task.fields[last]}"),
    ]
    initial_description = (
        f"Benchmark (round 1/{vote_rounds})" if vote_rounds > 1 else "Benchmark"
    )
    with Progress(*progress_columns, console=console) as progress:
        progress_task_id = progress.add_task(
            initial_description,
            total=task_total,
            completed=0,
            **_build_compact_progress_fields(
                completed_count=0,
                succeeded_count=0,
                failed_count=0,
                task_total=task_total,
                max_workers=effective_workers,
                elapsed_seconds=0.0,
                last_artifact=None,
            ),
        )

        completion_count = 0
        succeeded_count = 0
        failed_count = 0
        start_time = perf_counter()

        def on_task_complete(artifact) -> None:
            nonlocal completion_count, succeeded_count, failed_count
            completion_count += 1
            if artifact.succeeded:
                succeeded_count += 1
            else:
                failed_count += 1
            # Derive the "current round" from the cumulative completion count.
            # Worker order within a round is non-deterministic, but the round
            # boundary is exact: round k starts at completion = (k-1)*N+1 and
            # ends at completion = k*N (with N = task_count_per_round).
            if vote_rounds > 1 and task_count_per_round > 0:
                # ceil(completion / N), clamped to [1, vote_rounds]
                current_round = min(
                    vote_rounds,
                    (completion_count + task_count_per_round - 1) // task_count_per_round,
                )
                description = f"Benchmark (round {current_round}/{vote_rounds})"
            else:
                description = "Benchmark"
            progress.update(
                progress_task_id,
                completed=completion_count,
                description=description,
                refresh=True,
                **_build_compact_progress_fields(
                    completed_count=completion_count,
                    succeeded_count=succeeded_count,
                    failed_count=failed_count,
                    task_total=task_total,
                    max_workers=effective_workers,
                    elapsed_seconds=perf_counter() - start_time,
                    last_artifact=artifact,
                ),
            )

        try:
            run_output_dir, artifacts = run_benchmark(
                config=app_config,
                limit=limit,
                progress_callback=on_task_complete,
            )
        except (ValueError, FileExistsError) as exc:
            raise typer.BadParameter(str(exc), param_hint="run.run_id") from exc
        final_description = (
            f"Benchmark (round {vote_rounds}/{vote_rounds})"
            if vote_rounds > 1
            else "Benchmark"
        )
        progress.update(
            progress_task_id,
            completed=task_total,
            description=final_description,
            refresh=True,
            **_build_compact_progress_fields(
                completed_count=task_total,
                succeeded_count=succeeded_count,
                failed_count=failed_count,
                task_total=task_total,
                max_workers=effective_workers,
                elapsed_seconds=perf_counter() - start_time,
                last_artifact=artifacts[-1] if artifacts else None,
            ),
        )
    console.print(f"Run output: {run_output_dir}")
    console.print(f"Tasks attempted: {len(artifacts)}")
    console.print(f"Succeeded tasks: {sum(1 for item in artifacts if item.succeeded)}")


def _resolve_run_dir(run_root: Path, run_id: str | None) -> Path:
    """Resolve the run directory under ``run_root``.

    If ``run_id`` is supplied, the path must already exist. Otherwise pick the
    latest subdirectory whose name looks like a run timestamp (``YYYYMMDDT...``).
    """
    if not run_root.exists():
        raise typer.BadParameter(
            f"run_root does not exist: {run_root}", param_hint="run_root"
        )
    if run_id is not None:
        candidate = run_root / run_id
        if not candidate.exists():
            raise typer.BadParameter(
                f"run_id directory not found: {candidate}", param_hint="run_id"
            )
        return candidate

    candidates = [
        entry
        for entry in run_root.iterdir()
        if entry.is_dir() and entry.name[:8].isdigit()
    ]
    if not candidates:
        raise typer.BadParameter(
            f"no run directories found under {run_root}", param_hint="run_root"
        )
    return max(candidates, key=lambda p: p.name)


def _render_score_summary(run_score: RunScore) -> None:
    """Pretty-print the summary table + non-perfect detail to the console."""
    summary = Table(title=f"Score Summary  (run={run_score.run_id}, λ={run_score.lambda_penalty})")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Tasks", str(run_score.total_tasks))
    summary.add_row("Total score", f"{run_score.total_score:.4f}")
    summary.add_row(
        "Average score",
        f"{run_score.average_score:.4f}  (×100 = {run_score.average_score * 100:.2f})",
    )
    summary.add_row(
        "Perfect (=1.0)",
        f"{run_score.perfect_count}  ({run_score.perfect_count / max(run_score.total_tasks, 1) * 100:.1f}%)",
    )
    summary.add_row(
        "Partial (0,1)",
        f"{run_score.partial_count}  ({run_score.partial_count / max(run_score.total_tasks, 1) * 100:.1f}%)",
    )
    summary.add_row(
        "Zero (=0.0)",
        f"{run_score.zero_count}  ({run_score.zero_count / max(run_score.total_tasks, 1) * 100:.1f}%)",
    )
    console.print(summary)

    nonperfect = sorted(
        (t for t in run_score.tasks if t.score < 0.999),
        key=lambda t: (t.score, t.task_id),
    )
    if not nonperfect:
        return
    detail = Table(title="Non-perfect tasks (ascending by score)")
    detail.add_column("task_id")
    detail.add_column("score", justify="right")
    detail.add_column("recall", justify="right")
    detail.add_column("matched/gold/pred", justify="right")
    detail.add_column("status")
    for task in nonperfect:
        detail.add_row(
            task.task_id,
            f"{task.score:.3f}",
            f"{task.recall:.3f}",
            f"{task.matched_columns}/{task.gold_columns}/{task.predicted_columns}",
            task.status,
        )
    console.print(detail)


@app.command()
def score(
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Run directory name under run-root. Defaults to the latest run.",
    ),
    run_root: Path = typer.Option(
        ARTIFACTS_DIR / "docker-out-v2",
        "--run-root",
        help="Root directory containing per-run subdirectories.",
    ),
    gold_dir: Path = typer.Option(
        DATA_DIR / "public" / "output",
        "--gold-dir",
        help="Directory containing ground truth task_<id>/gold.csv.",
    ),
    lambda_penalty: float = typer.Option(
        DEFAULT_LAMBDA,
        "--lambda-penalty",
        min=0.0,
        help="Penalty weight λ in `Score = Recall - λ · (Extra / Predicted)`.",
    ),
    output_json: Path | None = typer.Option(
        None,
        "--output-json",
        help="Path to write the per-task score report. Defaults to <run-dir>/score_report.json.",
    ),
) -> None:
    """Score a benchmark run against ground-truth gold CSVs (rules §6.2 / §6.3)."""
    run_dir = _resolve_run_dir(run_root, run_id)
    if not gold_dir.exists():
        raise typer.BadParameter(
            f"gold_dir does not exist: {gold_dir}", param_hint="gold_dir"
        )
    run_score = score_run(
        run_dir=run_dir,
        gold_dir=gold_dir,
        lambda_penalty=lambda_penalty,
    )
    _render_score_summary(run_score)
    report_path = output_json if output_json is not None else run_dir / "score_report.json"
    write_score_report(run_score, report_path)
    console.print(f"📄 Detailed report: {report_path}")


def main() -> None:
    app()
