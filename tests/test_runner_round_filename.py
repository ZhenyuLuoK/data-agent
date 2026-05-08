"""Unit tests for runner._round_artifact_filename."""

from __future__ import annotations

from data_agent_baseline.run.runner import _round_artifact_filename


def test_round_one_always_writes_prediction() -> None:
    # Round 1 must write the baseline prediction.csv regardless of state.
    assert _round_artifact_filename(1, base_already_exists=False) == "prediction.csv"
    assert _round_artifact_filename(1, base_already_exists=True) == "prediction.csv"


def test_round_two_with_existing_base_writes_r2() -> None:
    assert _round_artifact_filename(2, base_already_exists=True) == "r2.csv"


def test_round_two_without_base_fills_in_prediction() -> None:
    # When round 1 produced nothing, round 2 must back-fill prediction.csv.
    assert _round_artifact_filename(2, base_already_exists=False) == "prediction.csv"


def test_round_three_with_existing_base_writes_r3() -> None:
    assert _round_artifact_filename(3, base_already_exists=True) == "r3.csv"


def test_round_three_without_base_fills_in_prediction() -> None:
    assert _round_artifact_filename(3, base_already_exists=False) == "prediction.csv"
