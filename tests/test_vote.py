"""Unit tests for run.vote — voting protocol over prediction/r2/r3 CSVs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent_baseline.run.vote import vote_all_tasks, vote_task


def _write_csv(path: Path, columns: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n")


# ---- vote_task --------------------------------------------------------------


def test_three_identical_keeps_prediction(tmp_path: Path) -> None:
    for name in ("prediction.csv", "r2.csv", "r3.csv"):
        _write_csv(tmp_path / name, ["v"], [["1"], ["2"]])
    original = (tmp_path / "prediction.csv").read_text()

    result = vote_task(tmp_path)

    assert result.winner_filename == "prediction.csv"
    assert result.winner_overwrote_prediction is False
    assert result.rule_applied == "majority"
    # prediction.csv left untouched.
    assert (tmp_path / "prediction.csv").read_text() == original


def test_majority_two_one_picks_earliest_majority(tmp_path: Path) -> None:
    # prediction differs; r2 and r3 agree → winner = r2, must overwrite prediction.
    _write_csv(tmp_path / "prediction.csv", ["v"], [["1"]])
    _write_csv(tmp_path / "r2.csv", ["v"], [["2"]])
    _write_csv(tmp_path / "r3.csv", ["v"], [["2"]])

    result = vote_task(tmp_path)

    assert result.winner_filename == "r2.csv"
    assert result.winner_overwrote_prediction is True
    assert result.rule_applied == "majority"
    assert (tmp_path / "prediction.csv").read_text() == (tmp_path / "r2.csv").read_text()


def test_three_different_falls_back_to_prediction(tmp_path: Path) -> None:
    _write_csv(tmp_path / "prediction.csv", ["v"], [["1"]])
    _write_csv(tmp_path / "r2.csv", ["v"], [["2"]])
    _write_csv(tmp_path / "r3.csv", ["v"], [["3"]])
    original = (tmp_path / "prediction.csv").read_text()

    result = vote_task(tmp_path)

    assert result.winner_filename == "prediction.csv"
    assert result.winner_overwrote_prediction is False
    assert result.rule_applied == "all_different"
    assert (tmp_path / "prediction.csv").read_text() == original


def test_only_prediction_present(tmp_path: Path) -> None:
    _write_csv(tmp_path / "prediction.csv", ["v"], [["1"]])

    result = vote_task(tmp_path)

    assert result.winner_filename == "prediction.csv"
    assert result.winner_overwrote_prediction is False
    assert result.rule_applied == "single_candidate"


def test_two_present_returns_first(tmp_path: Path) -> None:
    _write_csv(tmp_path / "prediction.csv", ["v"], [["1"]])
    _write_csv(tmp_path / "r2.csv", ["v"], [["999"]])

    result = vote_task(tmp_path)

    assert result.winner_filename == "prediction.csv"
    assert result.winner_overwrote_prediction is False
    assert result.rule_applied == "two_candidates"


def test_no_candidates_yields_none(tmp_path: Path) -> None:
    result = vote_task(tmp_path)

    assert result.winner_filename is None
    assert result.winner_overwrote_prediction is False
    assert result.rule_applied == "no_candidates"


def test_zero_byte_file_treated_as_missing(tmp_path: Path) -> None:
    (tmp_path / "prediction.csv").write_text("")  # 0 bytes
    _write_csv(tmp_path / "r2.csv", ["v"], [["1"]])
    _write_csv(tmp_path / "r3.csv", ["v"], [["1"]])

    result = vote_task(tmp_path)

    # Only r2 and r3 are valid → 2 candidates → first valid (r2) wins; no overwrite
    # of the broken prediction.csv since the rule only overwrites in the "majority"
    # branch.
    assert result.winner_filename == "r2.csv"
    assert result.rule_applied == "two_candidates"
    assert result.winner_overwrote_prediction is False


def test_majority_signature_robust_to_row_order(tmp_path: Path) -> None:
    # prediction has rows in one order, r2/r3 in another order — should still
    # vote together (signature is row-order-insensitive).
    _write_csv(tmp_path / "prediction.csv", ["v"], [["DIFF"]])
    _write_csv(tmp_path / "r2.csv", ["v"], [["1"], ["2"]])
    _write_csv(tmp_path / "r3.csv", ["v"], [["2"], ["1"]])

    result = vote_task(tmp_path)

    assert result.winner_filename == "r2.csv"
    assert result.rule_applied == "majority"
    assert result.winner_overwrote_prediction is True


# ---- vote_all_tasks ---------------------------------------------------------


def test_vote_all_tasks_writes_summary_and_skips_empty(tmp_path: Path) -> None:
    # Two task dirs with content + one empty dir that should be skipped.
    task_a = tmp_path / "task_001"
    task_b = tmp_path / "task_002"
    task_empty = tmp_path / "task_999"
    task_empty.mkdir()

    _write_csv(task_a / "prediction.csv", ["v"], [["1"]])
    _write_csv(task_b / "prediction.csv", ["v"], [["X"]])
    _write_csv(task_b / "r2.csv", ["v"], [["Y"]])
    _write_csv(task_b / "r3.csv", ["v"], [["Y"]])

    results = vote_all_tasks(tmp_path)

    assert set(results.keys()) == {"task_001", "task_002"}
    assert results["task_002"].winner_filename == "r2.csv"

    summary_path = tmp_path / "vote_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert "task_001" in summary
    assert "task_002" in summary
    assert summary["task_002"]["rule_applied"] == "majority"


def test_vote_all_tasks_handles_missing_dir(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist"
    results = vote_all_tasks(nonexistent)
    assert results == {}


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
