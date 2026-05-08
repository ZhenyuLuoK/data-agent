"""Unit tests for table_signature.normalize_cell / compute_table_signature."""

from __future__ import annotations

from data_agent_baseline.run.table_signature import (
    compute_table_signature,
    normalize_cell,
)


# ---- normalize_cell ---------------------------------------------------------


def test_numeric_string_quantizes_to_two_decimals() -> None:
    assert normalize_cell("4200000") == normalize_cell("4200000.00")
    assert normalize_cell("4200000") == "4200000.00"


def test_int_and_float_collide_with_string() -> None:
    assert normalize_cell(4200000) == normalize_cell("4200000.00")
    assert normalize_cell(4200000.0) == normalize_cell("4200000")


def test_string_is_case_sensitive() -> None:
    # The plan explicitly calls for case-sensitive string comparison.
    assert normalize_cell("East Asia") != normalize_cell("east asia")


def test_string_strip_and_newline_drop() -> None:
    assert normalize_cell("  hello  ") == "hello"
    assert normalize_cell("hello\r\n") == "hello"


def test_null_variants_collapse_to_empty() -> None:
    assert normalize_cell(None) == ""
    assert normalize_cell("") == ""
    assert normalize_cell("null") == ""
    assert normalize_cell("NULL") == ""
    assert normalize_cell("None") == ""
    assert normalize_cell("nan") == ""
    assert normalize_cell("NaN") == ""
    assert normalize_cell("<NA>") == ""


def test_bool_is_not_treated_as_number() -> None:
    assert normalize_cell(True) == "True"
    assert normalize_cell(False) == "False"
    assert normalize_cell(True) != normalize_cell(1)


# ---- compute_table_signature -----------------------------------------------


def test_column_order_does_not_affect_signature() -> None:
    sig_a = compute_table_signature(
        ["a", "b"],
        [[1, "x"], [2, "y"]],
    )
    sig_b = compute_table_signature(
        ["b", "a"],
        [["x", 1], ["y", 2]],
    )
    assert sig_a == sig_b


def test_row_order_does_not_affect_signature() -> None:
    sig_a = compute_table_signature(
        ["a", "b"],
        [[1, "x"], [2, "y"], [3, "z"]],
    )
    sig_b = compute_table_signature(
        ["a", "b"],
        [[3, "z"], [1, "x"], [2, "y"]],
    )
    assert sig_a == sig_b


def test_column_names_do_not_affect_signature() -> None:
    sig_a = compute_table_signature(
        ["foo", "bar"],
        [[1, "x"], [2, "y"]],
    )
    sig_b = compute_table_signature(
        ["alpha", "beta"],
        [[1, "x"], [2, "y"]],
    )
    assert sig_a == sig_b


def test_numeric_precision_in_table() -> None:
    sig_a = compute_table_signature(["v"], [["4200000"], ["3.14"]])
    sig_b = compute_table_signature(["v"], [["4200000.00"], ["3.140"]])
    assert sig_a == sig_b


def test_null_variants_collide_in_table() -> None:
    sig_a = compute_table_signature(["v"], [[""], ["null"], ["NaN"], [None]])
    sig_b = compute_table_signature(["v"], [[None], [""], [""], [""]])
    assert sig_a == sig_b


def test_different_values_yield_different_signatures() -> None:
    sig_a = compute_table_signature(["v"], [[1]])
    sig_b = compute_table_signature(["v"], [[2]])
    assert sig_a != sig_b


def test_empty_table_signature() -> None:
    assert compute_table_signature([], []) == ()
    assert compute_table_signature(["a"], []) == ()
