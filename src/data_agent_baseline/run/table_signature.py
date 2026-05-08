"""Table normalization & signature for cross-round answer voting.

This module is intentionally kept small and dependency-free (stdlib only) so
it can be exercised by lightweight unit tests without touching the heavy
LangGraph / dataset machinery.

Design notes (kept inline so future readers don't have to dig through the
plan doc):

* Voting is performed at *whole table* granularity. Two prediction CSVs are
  considered "the same answer" iff their normalized signatures match.
* The signature is column-name- and column-order-agnostic, and row-order-
  agnostic. We achieve this by:
    1. Normalizing every cell with ``normalize_cell``.
    2. For each column, sorting its normalized cells into a tuple.
    3. Sorting the per-column tuples themselves into a tuple of tuples.
* Numbers are quantized to 2 decimal places (HALF_UP) so that
  ``"4200000"`` and ``"4200000.00"`` collide. Booleans are NOT treated as
  numbers — that would map ``True`` to ``"1.00"`` which is rarely intended.
* A small set of textual null variants ({"", "null", "none", "nan", "nat",
  "<na>"}, case-insensitive) all collapse to the empty string ``""``.
"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

# Cells whose lowercased str() falls in this set are treated as "empty".
_NULL_TOKENS: frozenset[str] = frozenset({"", "null", "none", "nan", "nat", "<na>"})

_TWO_PLACES = Decimal("0.01")

# --- Date / datetime normalization helpers ---------------------------------
#
# Why bother: post-vote we want bytes-on-disk to look like the canonical
# format the grader expects, regardless of whether the model wrote
# "2024-3-1" / "2024/3/1" / "March 1, 2024" / "2024-03-01T08:00:00+08:00".
#
# Order of attempts (each falls through on failure, so ambiguous strings
# stay verbatim):
#   1. ISO 8601 datetime via ``datetime.fromisoformat`` (Python 3.11+ accepts
#      the "Z" suffix and most timezone forms). If tz-aware → convert to UTC
#      + suffix ``Z``. If naive datetime → keep ISO without inventing a tz.
#   2. ISO 8601 date with optional unpadded month/day (``YYYY-M-D``,
#      ``YYYY/M/D``) → emit ``YYYY-MM-DD``.
#   3. Long-form English date (``March 1, 2024`` / ``Mar 1 2024``) → emit
#      ``YYYY-MM-DD`` via ``%B %d, %Y`` / ``%b %d %Y`` strptime.
# Anything else returns ``None`` and the caller falls back to numeric / raw.

_DATE_ONLY_RE = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")
_LONG_DATE_FORMATS: tuple[str, ...] = (
    "%B %d, %Y",   # "March 1, 2024"
    "%B %d %Y",    # "March 1 2024"
    "%b %d, %Y",   # "Mar 1, 2024"
    "%b %d %Y",    # "Mar 1 2024"
    "%d %B %Y",    # "1 March 2024"
    "%d %b %Y",    # "1 Mar 2024"
)


def _try_normalize_datetime(text: str) -> str | None:
    """Attempt to normalize ``text`` as an ISO datetime.

    Returns the canonical form, or ``None`` if ``text`` doesn't look like
    one. Pure date strings (``2024-03-01``) are NOT handled here — they
    go through ``_try_normalize_date`` instead so we can keep the ``T``-
    presence check simple.
    """
    if "T" not in text and " " not in text:
        return None
    candidate = text.strip()
    # ``datetime.fromisoformat`` in 3.11+ accepts trailing ``Z``; below 3.11
    # we patch it manually so this code is portable.
    iso_candidate = candidate
    if iso_candidate.endswith("Z") or iso_candidate.endswith("z"):
        iso_candidate = iso_candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso_candidate)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt_utc.isoformat(timespec="seconds") + "Z"
    # Naive datetime: keep ISO form without inventing a timezone.
    return dt.isoformat(timespec="seconds")


def _try_normalize_date(text: str) -> str | None:
    """Attempt to normalize ``text`` as a calendar date (no time).

    Returns ``YYYY-MM-DD`` or ``None`` when ``text`` doesn't match any
    known shape. We keep this conservative — anything ambiguous (US
    ``MM/DD/YYYY`` vs EU ``DD/MM/YYYY``) is left untouched to avoid
    silently swapping month/day.
    """
    candidate = text.strip()

    match = _DATE_ONLY_RE.match(candidate)
    if match is not None:
        year, month, day = match.groups()
        try:
            dt = datetime(int(year), int(month), int(day))
        except ValueError:
            return None
        return dt.strftime("%Y-%m-%d")

    # Long-form English: try each format until one parses.
    for fmt in _LONG_DATE_FORMATS:
        try:
            dt = datetime.strptime(candidate, fmt)
        except ValueError:
            continue
        return dt.strftime("%Y-%m-%d")

    return None


def normalize_cell(value: Any) -> str:
    """Normalize a single cell value to a canonical string form.

    Rules (in priority order):
      * ``None`` → ``""``
      * ``bool`` → ``"True"`` / ``"False"`` (NOT treated as a number)
      * Numeric (int / float / Decimal / numeric string) → quantize to
        2 decimal places, ROUND_HALF_UP, return ``str(Decimal)``.
      * Everything else → ``str(value)`` then ``strip``, drop CR/LF; if
        the lowercased result is one of the null tokens, return ``""``.
    """

    if value is None:
        return ""

    # Booleans are a subclass of int in Python; intercept BEFORE the numeric
    # branch so True/False don't get coerced to "1.00" / "0.00".
    if isinstance(value, bool):
        return "True" if value else "False"

    # Direct numeric types: int / float / Decimal.
    if isinstance(value, (int, Decimal)):
        try:
            return str(Decimal(value).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError):
            pass  # fall through to string handling
    elif isinstance(value, float):
        # Skip NaN / inf — those become the textual "nan"/"inf" branch below
        # via str() and get caught by the null-token set (for nan) or kept
        # as "inf" (rare edge case, fine to keep verbatim).
        if value != value:  # NaN
            return ""
        try:
            return str(Decimal(repr(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError):
            pass  # fall through

    # String / fallback path.
    text = str(value).replace("\r", "").replace("\n", "").strip()
    if text.lower() in _NULL_TOKENS:
        return ""

    # Try to interpret the cleaned string as a number too. CSV readers give
    # everything back as ``str``, so this is the hot path for prediction.csv.
    # Numbers are tried BEFORE date because numeric strings never contain
    # ``-`` or ``/`` separators (Decimal will reject ``2024-3-1``).
    try:
        return str(Decimal(text).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        pass

    # Date / datetime canonicalization. Order matters: try datetime first
    # (it requires ``T`` or whitespace separator), then plain date. Anything
    # we can't confidently parse is left verbatim — do NOT guess US vs EU
    # date order, do NOT touch arbitrary text.
    dt_norm = _try_normalize_datetime(text)
    if dt_norm is not None:
        return dt_norm
    date_norm = _try_normalize_date(text)
    if date_norm is not None:
        return date_norm

    return text


def compute_table_signature(
    columns: list[str],
    rows: list[list[Any]],
) -> tuple[tuple[str, ...], ...]:
    """Compute an order-insensitive signature for a tabular answer.

    The signature is a sorted tuple of "per-column signatures", where each
    per-column signature is the sorted tuple of that column's normalized
    cells. Column names and column order do NOT participate.

    Empty input (no columns or no rows) collapses to an empty tuple — two
    empty tables are considered identical.
    """

    if not columns or not rows:
        # Distinguish "no columns" vs "columns but zero rows": if there are
        # columns declared, still build per-column empty tuples so a table
        # with the same shape but no rows is distinguishable from a totally
        # empty result. We pick the simpler "empty" semantics here because
        # downstream voting treats both as "no real answer".
        return ()

    column_count = len(columns)
    per_column: list[tuple[str, ...]] = []
    for col_index in range(column_count):
        cells: list[str] = []
        for row in rows:
            cell = row[col_index] if col_index < len(row) else ""
            cells.append(normalize_cell(cell))
        per_column.append(tuple(sorted(cells)))

    return tuple(sorted(per_column))


def read_prediction_csv(path: Path) -> tuple[list[str], list[list[str]]] | None:
    """Read a prediction CSV; return (columns, rows) or None on failure.

    Returns ``None`` if:
      * the file does not exist,
      * the file is 0 bytes,
      * the file cannot be parsed as CSV.

    Otherwise returns ``(columns, rows)`` where every cell is a ``str``
    (since ``csv`` always yields strings).
    """

    if not path.exists():
        return None
    try:
        if path.stat().st_size == 0:
            return None
    except OSError:
        return None

    try:
        with path.open("r", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                return None
            rows = [list(row) for row in reader]
    except (OSError, csv.Error, UnicodeDecodeError):
        return None

    return list(header), rows


def normalize_prediction_csv(path: Path) -> bool:
    """Apply ``normalize_cell`` to every cell in a prediction CSV in place.

    This is the deterministic safety net that runs after voting picks a
    winner: regardless of what the LLM wrote (``5519.475171445073``,
    ``+14.925``, ``2024-3-1``, ``March 1, 2024``, ``null``, …), the bytes
    on disk that the grader sees end up in the canonical form the
    grader's normalization rule expects.

    Behaviour:
      * If ``path`` is missing / empty / unparseable → returns ``False``
        without writing anything.
      * Otherwise reads the CSV, normalizes every data cell (column
        headers are NOT touched — the grader matches column-value
        signatures, not header text), and atomically writes the result
        back to ``path`` via ``tmp + os.replace``.
      * Returns ``True`` iff a write actually happened. The function
        does NOT short-circuit when "nothing changed" — running the
        write makes the call idempotent and avoids subtle bugs from
        comparing pre/post strings (CSV quoting differences, trailing
        newlines, etc.).

    The header row is passed through verbatim. Cells that don't match
    any normalization rule (arbitrary text, error strings like
    ``"undefined (division by zero)"``) are left as-is — the schema
    layer / answer-tool guard is responsible for keeping garbage out;
    this layer is only about format canonicalization.
    """

    parsed = read_prediction_csv(path)
    if parsed is None:
        return False
    columns, rows = parsed

    normalized_rows: list[list[str]] = []
    for row in rows:
        # Pad short rows to the column width so grader doesn't see ragged
        # output; truncate over-long rows to header width for the same
        # reason. This matches what most grader-side CSV readers do.
        new_row: list[str] = []
        for col_index in range(len(columns)):
            cell = row[col_index] if col_index < len(row) else ""
            new_row.append(normalize_cell(cell))
        normalized_rows.append(new_row)

    tmp_path = path.with_name(path.name + ".norm.tmp")
    try:
        with tmp_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(normalized_rows)
        os.replace(tmp_path, path)
    except OSError:
        # Best-effort cleanup; never raise out of the normalization layer.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        return False
    return True
