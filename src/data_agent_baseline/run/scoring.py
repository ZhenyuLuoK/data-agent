"""Score prediction CSVs against ground-truth gold CSVs.

Implements the official KDD Cup 2026 DataAgent-Bench scoring rules
(Section 6.2 / 6.3):

* **Column-signature matching (6.2)**
    For every column, sort the cell values and freeze them into a tuple
    ("column signature"). Match prediction columns against gold columns by
    signature alone — column names and row order are intentionally ignored.
    Duplicate columns are matched as a multiset (a signature appearing N
    times in gold must appear at least N times in prediction to fully
    contribute).

* **Score with redundancy penalty (6.3)**
    ``Recall = matched / gold_columns``
    ``Score  = max(0, Recall - λ · (extra / predicted_columns))``
    where ``extra = predicted_columns - matched``. The penalty discourages
    the agent from dumping large irrelevant columns to inflate recall.

This module is intentionally self-contained and does NOT reuse
``run/table_signature.py``: that helper is tuned for the voting protocol
which tolerates many input shapes; scoring needs strict, lossless CSV
parsing that preserves every column.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

DEFAULT_LAMBDA: float = 0.5

# Cell values that should be treated as "empty" before signature hashing.
# Kept tiny on purpose — anything fancier risks masking real answer
# differences (e.g. a question that legitimately asks for the string "NA").
_NULL_LITERALS: frozenset[str] = frozenset({"nan", "null", "none", "na"})


@dataclass(frozen=True, slots=True)
class TaskScore:
    """Per-task scoring result."""

    task_id: str
    score: float
    recall: float
    matched_columns: int
    gold_columns: int
    predicted_columns: int
    extra_columns: int
    status: str  # "OK" / "PRED_MISSING" / "GOLD_MISSING"

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "score": self.score,
            "recall": self.recall,
            "matched_columns": self.matched_columns,
            "gold_columns": self.gold_columns,
            "predicted_columns": self.predicted_columns,
            "extra_columns": self.extra_columns,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class RunScore:
    """Aggregated scoring result over a benchmark run."""

    run_id: str
    lambda_penalty: float
    total_tasks: int
    total_score: float
    average_score: float
    perfect_count: int
    partial_count: int
    zero_count: int
    tasks: tuple[TaskScore, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "lambda_penalty": self.lambda_penalty,
            "total_tasks": self.total_tasks,
            "total_score": self.total_score,
            "average_score": self.average_score,
            "perfect_count": self.perfect_count,
            "partial_count": self.partial_count,
            "zero_count": self.zero_count,
            "tasks": [t.to_dict() for t in self.tasks],
        }


def normalise_cell(value: object) -> str:
    """Normalise one cell value before signature hashing.

    Rules (kept conservative on purpose):
      * ``None`` -> empty string
      * Strip leading/trailing whitespace
      * Common null literals (case-insensitive: nan/null/none/na) -> ""
      * Everything else stays as-is (no case-folding, no number coercion)
    """
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in _NULL_LITERALS:
        return ""
    return text


def _read_columns(csv_path: Path) -> list[list[str]] | None:
    """Read a CSV file and return its columns (list of cell-strings per column).

    Returns ``None`` if the file is missing, unreadable, or has no header row.
    Rows shorter than the header are right-padded with ``""``; rows longer
    than the header are truncated (this matches what a strict csv.reader
    would naturally produce for downstream column-signature hashing).
    """
    if not csv_path.exists():
        return None
    try:
        with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
    except OSError:
        return None
    if not rows:
        return None
    header = rows[0]
    column_count = len(header)
    if column_count == 0:
        return None
    columns: list[list[str]] = [[] for _ in range(column_count)]
    for row in rows[1:]:
        for column_index in range(column_count):
            cell = row[column_index] if column_index < len(row) else ""
            columns[column_index].append(normalise_cell(cell))
    return columns


def column_signatures(csv_path: Path) -> list[tuple[str, ...]] | None:
    """Return per-column signatures (sorted-tuple of normalised cells).

    ``None`` means the file could not be parsed into at least a header.
    """
    columns = _read_columns(csv_path)
    if columns is None:
        return None
    return [tuple(sorted(column)) for column in columns]


def score_task(
    *,
    task_id: str,
    gold_csv: Path,
    prediction_csv: Path,
    lambda_penalty: float = DEFAULT_LAMBDA,
) -> TaskScore:
    """Score a single task by comparing prediction.csv against gold.csv."""
    if lambda_penalty < 0:
        raise ValueError(f"lambda_penalty must be >= 0, got {lambda_penalty}")

    gold_signatures = column_signatures(gold_csv)
    if gold_signatures is None:
        # Should never happen for a well-formed dataset, but we still
        # return a zero-score record so callers can surface the issue.
        return TaskScore(
            task_id=task_id,
            score=0.0,
            recall=0.0,
            matched_columns=0,
            gold_columns=0,
            predicted_columns=0,
            extra_columns=0,
            status="GOLD_MISSING",
        )

    gold_column_count = len(gold_signatures)
    prediction_signatures = column_signatures(prediction_csv)
    if prediction_signatures is None:
        return TaskScore(
            task_id=task_id,
            score=0.0,
            recall=0.0,
            matched_columns=0,
            gold_columns=gold_column_count,
            predicted_columns=0,
            extra_columns=0,
            status="PRED_MISSING",
        )

    predicted_column_count = len(prediction_signatures)
    gold_counter: Counter[tuple[str, ...]] = Counter(gold_signatures)
    pred_counter: Counter[tuple[str, ...]] = Counter(prediction_signatures)

    matched = 0
    for signature, gold_count in gold_counter.items():
        matched += min(gold_count, pred_counter.get(signature, 0))

    extra = predicted_column_count - matched
    recall = matched / gold_column_count if gold_column_count > 0 else 0.0
    penalty = (
        lambda_penalty * (extra / predicted_column_count)
        if predicted_column_count > 0
        else 0.0
    )
    score = max(0.0, recall - penalty)

    return TaskScore(
        task_id=task_id,
        score=score,
        recall=recall,
        matched_columns=matched,
        gold_columns=gold_column_count,
        predicted_columns=predicted_column_count,
        extra_columns=extra,
        status="OK",
    )


def score_run(
    *,
    run_dir: Path,
    gold_dir: Path,
    lambda_penalty: float = DEFAULT_LAMBDA,
    task_ids: Iterable[str] | None = None,
) -> RunScore:
    """Score a benchmark run by comparing every gold task against the run.

    The set of tasks scored is determined by ``gold_dir`` (one subdirectory
    per ``task_<id>``), unless ``task_ids`` is provided.
    """
    if not gold_dir.exists():
        raise FileNotFoundError(f"gold directory does not exist: {gold_dir}")

    if task_ids is None:
        scored_task_ids = sorted(
            entry.name
            for entry in gold_dir.iterdir()
            if entry.is_dir() and entry.name.startswith("task_")
        )
    else:
        scored_task_ids = sorted(task_ids)

    task_scores: list[TaskScore] = []
    for task_id in scored_task_ids:
        gold_csv = gold_dir / task_id / "gold.csv"
        prediction_csv = run_dir / task_id / "prediction.csv"
        task_scores.append(
            score_task(
                task_id=task_id,
                gold_csv=gold_csv,
                prediction_csv=prediction_csv,
                lambda_penalty=lambda_penalty,
            )
        )

    total_tasks = len(task_scores)
    total_score = sum(t.score for t in task_scores)
    average_score = total_score / total_tasks if total_tasks > 0 else 0.0
    perfect = sum(1 for t in task_scores if t.score >= 0.999)
    zero = sum(1 for t in task_scores if t.score == 0.0)
    partial = total_tasks - perfect - zero

    return RunScore(
        run_id=run_dir.name,
        lambda_penalty=lambda_penalty,
        total_tasks=total_tasks,
        total_score=total_score,
        average_score=average_score,
        perfect_count=perfect,
        partial_count=partial,
        zero_count=zero,
        tasks=tuple(task_scores),
    )


def write_score_report(run_score: RunScore, output_path: Path) -> None:
    """Persist a ``RunScore`` as a JSON report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(run_score.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
