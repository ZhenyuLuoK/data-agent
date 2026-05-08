"""Unit tests for ``data_agent_baseline.run.scoring``."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from data_agent_baseline.run.scoring import (
    DEFAULT_LAMBDA,
    column_signatures,
    normalise_cell,
    score_run,
    score_task,
    write_score_report,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


# --------------------------------------------------------------------------- #
# normalise_cell
# --------------------------------------------------------------------------- #

def test_normalise_cell_handles_none_and_strip():
    assert normalise_cell(None) == ""
    assert normalise_cell("  hello  ") == "hello"
    assert normalise_cell("") == ""


def test_normalise_cell_collapses_null_literals_case_insensitive():
    for literal in ["nan", "NaN", "NULL", "None", "na", " NA "]:
        assert normalise_cell(literal) == ""


def test_normalise_cell_preserves_meaningful_strings():
    # We don't want the scorer to accidentally collapse legitimate answers
    # like "0" or " false " into the empty string.
    assert normalise_cell("0") == "0"
    assert normalise_cell("false") == "false"
    assert normalise_cell("FALSE") == "FALSE"  # no case-folding outside null literals


# --------------------------------------------------------------------------- #
# column_signatures
# --------------------------------------------------------------------------- #

def test_column_signatures_sort_per_column(tmp_path: Path):
    csv_path = tmp_path / "x.csv"
    _write_csv(csv_path, ["a", "b"], [["3", "y"], ["1", "x"], ["2", "z"]])
    sigs = column_signatures(csv_path)
    assert sigs == [("1", "2", "3"), ("x", "y", "z")]


def test_column_signatures_returns_none_for_missing_file(tmp_path: Path):
    assert column_signatures(tmp_path / "nope.csv") is None


def test_column_signatures_returns_none_for_empty_file(tmp_path: Path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")
    assert column_signatures(csv_path) is None


def test_column_signatures_pads_short_rows(tmp_path: Path):
    csv_path = tmp_path / "ragged.csv"
    # Header has 3 cols; one row is short.
    _write_csv(csv_path, ["a", "b", "c"], [["1", "x", "p"], ["2", "y"], ["3", "z", "r"]])
    sigs = column_signatures(csv_path)
    # Third column gets "" injected for the short row.
    assert sigs[2] == ("", "p", "r")


# --------------------------------------------------------------------------- #
# score_task
# --------------------------------------------------------------------------- #

def test_score_task_perfect_match(tmp_path: Path):
    gold = tmp_path / "gold" / "g.csv"
    pred = tmp_path / "pred" / "p.csv"
    _write_csv(gold, ["v"], [["a"], ["b"], ["c"]])
    _write_csv(pred, ["whatever"], [["c"], ["a"], ["b"]])  # different col name + order
    result = score_task(task_id="t1", gold_csv=gold, prediction_csv=pred)
    assert result.score == 1.0
    assert result.recall == 1.0
    assert result.matched_columns == 1
    assert result.extra_columns == 0
    assert result.status == "OK"


def test_score_task_extra_columns_penalised(tmp_path: Path):
    gold = tmp_path / "g.csv"
    pred = tmp_path / "p.csv"
    _write_csv(gold, ["v"], [["a"]])
    # Predicted has the matching column + 3 extra noise columns.
    _write_csv(
        pred,
        ["v", "noise1", "noise2", "noise3"],
        [["a", "x", "y", "z"]],
    )
    result = score_task(task_id="t1", gold_csv=gold, prediction_csv=pred, lambda_penalty=0.5)
    # recall=1.0; penalty=0.5 * (3/4) = 0.375 → score = 0.625
    assert result.recall == pytest.approx(1.0)
    assert result.score == pytest.approx(0.625)
    assert result.extra_columns == 3


def test_score_task_zero_recall_with_unrelated_columns(tmp_path: Path):
    gold = tmp_path / "g.csv"
    pred = tmp_path / "p.csv"
    _write_csv(gold, ["v"], [["a"], ["b"]])
    _write_csv(pred, ["v"], [["x"], ["y"]])  # same col name but content differs → no match
    result = score_task(task_id="t1", gold_csv=gold, prediction_csv=pred)
    assert result.score == 0.0
    assert result.recall == 0.0
    assert result.matched_columns == 0


def test_score_task_clamped_to_zero(tmp_path: Path):
    """Heavy extras must not push the score below zero."""
    gold = tmp_path / "g.csv"
    pred = tmp_path / "p.csv"
    _write_csv(gold, ["v"], [["a"]])
    # 1 matching column + 99 noise columns: recall=1, penalty=0.5*(99/100)=0.495 → 0.505
    _write_csv(pred, ["v"] + [f"n{i}" for i in range(99)], [["a"] + ["?"] * 99])
    result = score_task(task_id="t1", gold_csv=gold, prediction_csv=pred, lambda_penalty=0.5)
    assert result.score == pytest.approx(0.505)
    # And again with a much higher λ that would naively go negative.
    result_big_lambda = score_task(
        task_id="t1", gold_csv=gold, prediction_csv=pred, lambda_penalty=10.0
    )
    assert result_big_lambda.score == 0.0


def test_score_task_duplicate_columns_multiset(tmp_path: Path):
    gold = tmp_path / "g.csv"
    pred = tmp_path / "p.csv"
    # Gold has the same column signature twice.
    _write_csv(gold, ["x", "y"], [["1", "1"], ["2", "2"]])
    # Prediction only has it once → matched=1, extra=0, recall=0.5
    _write_csv(pred, ["only"], [["1"], ["2"]])
    result = score_task(task_id="t1", gold_csv=gold, prediction_csv=pred)
    assert result.matched_columns == 1
    assert result.recall == 0.5
    assert result.score == 0.5  # extra=0 so no penalty


def test_score_task_prediction_missing(tmp_path: Path):
    gold = tmp_path / "g.csv"
    _write_csv(gold, ["v"], [["a"]])
    result = score_task(
        task_id="t1",
        gold_csv=gold,
        prediction_csv=tmp_path / "missing.csv",
    )
    assert result.score == 0.0
    assert result.predicted_columns == 0
    assert result.status == "PRED_MISSING"


def test_score_task_gold_missing(tmp_path: Path):
    pred = tmp_path / "p.csv"
    _write_csv(pred, ["v"], [["a"]])
    result = score_task(
        task_id="t1",
        gold_csv=tmp_path / "missing.csv",
        prediction_csv=pred,
    )
    assert result.score == 0.0
    assert result.gold_columns == 0
    assert result.status == "GOLD_MISSING"


def test_score_task_negative_lambda_rejected(tmp_path: Path):
    gold = tmp_path / "g.csv"
    pred = tmp_path / "p.csv"
    _write_csv(gold, ["v"], [["a"]])
    _write_csv(pred, ["v"], [["a"]])
    with pytest.raises(ValueError):
        score_task(task_id="t", gold_csv=gold, prediction_csv=pred, lambda_penalty=-0.1)


# --------------------------------------------------------------------------- #
# score_run + write_score_report
# --------------------------------------------------------------------------- #

def test_score_run_aggregates_and_writes_report(tmp_path: Path):
    gold_dir = tmp_path / "gold"
    run_dir = tmp_path / "runs" / "20260101T000000Z"

    # task_a: perfect
    _write_csv(gold_dir / "task_a" / "gold.csv", ["v"], [["1"], ["2"]])
    _write_csv(run_dir / "task_a" / "prediction.csv", ["x"], [["2"], ["1"]])

    # task_b: perfect content but with one extra column → partial
    _write_csv(gold_dir / "task_b" / "gold.csv", ["v"], [["x"]])
    _write_csv(run_dir / "task_b" / "prediction.csv", ["v", "extra"], [["x", "noise"]])

    # task_c: prediction missing → zero
    _write_csv(gold_dir / "task_c" / "gold.csv", ["v"], [["only"]])
    # (no prediction.csv written)

    run_score = score_run(run_dir=run_dir, gold_dir=gold_dir, lambda_penalty=0.5)
    assert run_score.total_tasks == 3
    assert run_score.perfect_count == 1
    assert run_score.partial_count == 1
    assert run_score.zero_count == 1
    # 1.0 + 0.75 + 0.0 = 1.75
    assert run_score.total_score == pytest.approx(1.75)
    assert run_score.average_score == pytest.approx(1.75 / 3)

    report_path = tmp_path / "report.json"
    write_score_report(run_score, report_path)
    assert report_path.exists()
    payload = report_path.read_text(encoding="utf-8")
    assert '"task_a"' in payload
    assert '"PRED_MISSING"' in payload


def test_score_run_uses_default_lambda(tmp_path: Path):
    gold_dir = tmp_path / "gold"
    run_dir = tmp_path / "run"
    _write_csv(gold_dir / "task_a" / "gold.csv", ["v"], [["x"]])
    _write_csv(run_dir / "task_a" / "prediction.csv", ["v"], [["x"]])
    run_score = score_run(run_dir=run_dir, gold_dir=gold_dir)
    assert run_score.lambda_penalty == DEFAULT_LAMBDA


def test_score_run_explicit_task_ids_filter(tmp_path: Path):
    gold_dir = tmp_path / "gold"
    run_dir = tmp_path / "run"
    for tid in ("task_a", "task_b"):
        _write_csv(gold_dir / tid / "gold.csv", ["v"], [["x"]])
        _write_csv(run_dir / tid / "prediction.csv", ["v"], [["x"]])
    run_score = score_run(
        run_dir=run_dir,
        gold_dir=gold_dir,
        task_ids=["task_a"],
    )
    assert run_score.total_tasks == 1
    assert run_score.tasks[0].task_id == "task_a"


def test_score_run_raises_when_gold_dir_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        score_run(run_dir=tmp_path, gold_dir=tmp_path / "nope")
