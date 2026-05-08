"""``inspect_data``: one-shot schema + statistics profile of a tabular file.

Why this exists (data point from 20260506T010810Z run):

* 76 of 121 ``execute_python`` calls (63%) were doing nothing more than
  ``df = pd.read_csv(...); print(df.head()); print(df.dtypes); print(df.shape)``
  — pure schema/profile probing the LLM does to understand a file before
  it can write a real query.
* Each such probe burns one full LLM round (~30s + prompt tokens) for
  information that can be computed deterministically in <100ms.

This tool returns the shape the LLM was already trying to assemble by
hand: per-column dtype, null count, distinct count, sample values, and
numeric min/max — all in one call. Backends:

* ``.csv`` / ``.tsv``                — stdlib ``csv`` + manual coercion
* ``.json`` / ``.jsonl`` / ``.ndjson`` — stdlib ``json`` + record flattening
* ``.sqlite`` / ``.db`` (with a ``table`` arg) — sqlite ``PRAGMA``-based
  schema + ``SELECT`` for stats

We deliberately avoid pulling in pandas here even though it would shrink
the implementation: doing so would (a) add a ~500ms cold-start cost per
call, and (b) make this tool's failure modes harder to reason about
(pandas dtype inference is full of edge cases the LLM would then have to
debug). The hand-rolled coercion below is boring on purpose.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


# Default cap on sample values per column. 5 is enough to convey a shape
# (e.g. "looks like ISO dates" vs "looks like enum codes") without bloating
# the response — and it matches the typical executor "df.head()" intuition.
_DEFAULT_SAMPLE_SIZE = 5

# When a column has more distinct values than this, we stop tracking the
# full set and just report ``unique_count`` as ">= cap" — avoids O(rows)
# memory blow-up on free-form text columns.
_UNIQUE_TRACKING_CAP = 5_000


class InspectDataError(ValueError):
    """Raised for any user-facing inspect_data failure.

    Distinct from ValueError so the LangGraph ToolNode wraps it as
    ``InspectDataError: <msg>`` — easier for the LLM to branch on than
    a generic exception.
    """


# ---------- Loaders --------------------------------------------------------


def _load_csv_like(path: Path, *, delimiter: str) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _load_json_records(path: Path) -> tuple[list[str], list[list[Any]]]:
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        if not payload:
            return [], []
        if not all(isinstance(item, dict) for item in payload):
            raise InspectDataError(
                "JSON list must contain objects (records); got non-object element."
            )
        columns: list[str] = []
        seen_keys: set[str] = set()
        for record in payload:
            for key in record:
                if key not in seen_keys:
                    seen_keys.add(key)
                    columns.append(key)
        rows = [[record.get(col) for col in columns] for record in payload]
        return columns, rows
    if isinstance(payload, dict) and payload and all(
        isinstance(value, list) for value in payload.values()
    ):
        columns = list(payload.keys())
        length = len(next(iter(payload.values())))
        if not all(len(value) == length for value in payload.values()):
            raise InspectDataError(
                "JSON dict-of-lists has unequal column lengths; cannot profile."
            )
        rows = [[payload[col][idx] for col in columns] for idx in range(length)]
        return columns, rows
    raise InspectDataError(
        "Unsupported JSON shape for inspect_data. Expected list of objects "
        "or dict whose values are equal-length lists. For nested JSON, use "
        "read_json + execute_python instead."
    )


def _load_jsonl(path: Path) -> tuple[list[str], list[list[Any]]]:
    columns: list[str] = []
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    with path.open() as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InspectDataError(
                    f"JSONL parse error on line {line_no}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise InspectDataError(f"JSONL line {line_no} is not an object.")
            for key in record:
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
            records.append(record)
    rows = [[record.get(col) for col in columns] for record in records]
    return columns, rows


# ---------- Per-column statistics -----------------------------------------


def _coerce_value(raw: Any) -> tuple[str | None, Any]:
    """Return ``(dtype_label, coerced_value)`` for a single cell.

    ``dtype_label`` ∈ {"int", "float", "bool", "null", "string"} —
    we sample-vote across the column to derive the column dtype. Coerced
    value is used for min/max calculation when the column votes numeric.

    Treatment of empty strings: counted as ``"null"`` to match how CSVs
    usually encode missing values, *except* when the column is fully
    string-typed elsewhere (the column-level reconciliation handles that).
    """

    if raw is None:
        return "null", None
    if isinstance(raw, bool):
        # bool is a subclass of int — must check first.
        return "bool", raw
    if isinstance(raw, int):
        return "int", raw
    if isinstance(raw, float):
        return "float", raw
    if isinstance(raw, str):
        if raw == "":
            return "null", None
        # Try numeric coercion; fall back to string.
        try:
            return "int", int(raw)
        except ValueError:
            pass
        try:
            return "float", float(raw)
        except ValueError:
            pass
        return "string", raw
    # Lists/dicts/etc — opaque, treat as string for sample purposes.
    return "string", repr(raw)


def _reconcile_column_dtype(per_cell_dtypes: Counter) -> str:
    """Collapse per-cell dtype votes to one column-level label.

    Rules (in order):
    * if all non-null cells agree → that dtype
    * if int + float coexist → ``"float"`` (numeric promotion)
    * if any cell is ``"string"`` and others are numeric → ``"mixed"``
      (signals to the LLM that CAST is needed before arithmetic)
    * fully null column → ``"null"``
    * single-class columns → that class
    """

    non_null_classes = {
        cls for cls, count in per_cell_dtypes.items() if count > 0 and cls != "null"
    }
    if not non_null_classes:
        return "null"
    if non_null_classes == {"int"}:
        return "int"
    if non_null_classes == {"float"} or non_null_classes == {"int", "float"}:
        return "float"
    if non_null_classes == {"bool"}:
        return "bool"
    if non_null_classes == {"string"}:
        return "string"
    # Anything else — string mixed with numeric, etc.
    return "mixed"


def _profile_columns(
    column_names: list[str],
    rows: list[list[Any]],
    *,
    sample_size: int,
) -> list[dict[str, Any]]:
    if not column_names:
        return []

    column_count = len(column_names)
    per_col_dtypes: list[Counter] = [Counter() for _ in range(column_count)]
    per_col_null: list[int] = [0] * column_count
    per_col_unique: list[set[Any] | None] = [set() for _ in range(column_count)]
    per_col_samples: list[list[Any]] = [[] for _ in range(column_count)]
    per_col_numeric_min: list[float | None] = [None] * column_count
    per_col_numeric_max: list[float | None] = [None] * column_count

    for row in rows:
        # Pad short rows with None so ragged json-record inputs still profile.
        for col_idx in range(column_count):
            raw = row[col_idx] if col_idx < len(row) else None
            dtype_label, coerced = _coerce_value(raw)
            per_col_dtypes[col_idx][dtype_label] += 1

            if dtype_label == "null":
                per_col_null[col_idx] += 1
                continue

            # Track unique values up to the cap; beyond that, we lose
            # exactness but keep memory bounded. The original raw value
            # is what we record, not the coerced one — the LLM benefits
            # from seeing "01" vs 1 distinctly when the source CSV did.
            unique_set = per_col_unique[col_idx]
            if unique_set is not None:
                unique_set.add(raw)
                if len(unique_set) > _UNIQUE_TRACKING_CAP:
                    per_col_unique[col_idx] = None  # stop tracking

            samples = per_col_samples[col_idx]
            if len(samples) < sample_size:
                samples.append(raw)

            if dtype_label in {"int", "float"} and isinstance(coerced, (int, float)):
                current_min = per_col_numeric_min[col_idx]
                current_max = per_col_numeric_max[col_idx]
                if current_min is None or coerced < current_min:
                    per_col_numeric_min[col_idx] = coerced
                if current_max is None or coerced > current_max:
                    per_col_numeric_max[col_idx] = coerced

    profiles: list[dict[str, Any]] = []
    for col_idx, name in enumerate(column_names):
        column_dtype = _reconcile_column_dtype(per_col_dtypes[col_idx])
        unique_set = per_col_unique[col_idx]
        unique_repr: int | str
        if unique_set is None:
            unique_repr = f">={_UNIQUE_TRACKING_CAP}"
        else:
            unique_repr = len(unique_set)

        col_record: dict[str, Any] = {
            "name": name,
            "dtype": column_dtype,
            "null_count": per_col_null[col_idx],
            "unique_count": unique_repr,
            "sample_values": list(per_col_samples[col_idx]),
        }
        if column_dtype in {"int", "float"}:
            col_record["min"] = per_col_numeric_min[col_idx]
            col_record["max"] = per_col_numeric_max[col_idx]
        profiles.append(col_record)
    return profiles


# ---------- sqlite path ----------------------------------------------------


def _profile_sqlite_table(
    db_path: Path,
    table: str,
    *,
    sample_size: int,
) -> dict[str, Any]:
    """Profile a single sqlite table via PRAGMA + SELECT.

    Used when the caller passes a ``.sqlite`` / ``.db`` path with a
    ``table`` argument. We deliberately keep the SQL surface tiny:
    ``PRAGMA table_info`` for the schema, ``COUNT(*)`` for the row count,
    one ``SELECT *`` for the sample, and one ``SELECT COUNT(DISTINCT col)``
    per column. For the largest dabench sqlite (a few hundred KB) this is
    a sub-100ms operation.
    """

    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        # Validate the table exists before issuing untrusted ``table`` into SQL.
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if table not in existing:
            raise InspectDataError(
                f"Table {table!r} not found in {db_path.name}. "
                f"Available tables: {sorted(existing)}."
            )

        # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
        info_rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        column_names = [r[1] for r in info_rows]
        declared_types = {r[1]: (r[2] or "").lower() or "unknown" for r in info_rows}

        row_count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

        sample_rows = conn.execute(
            f'SELECT * FROM "{table}" LIMIT ?', (sample_size,)
        ).fetchall()

        column_profiles: list[dict[str, Any]] = []
        for col_idx, col_name in enumerate(column_names):
            null_count = conn.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{col_name}" IS NULL'
            ).fetchone()[0]
            unique_count = conn.execute(
                f'SELECT COUNT(DISTINCT "{col_name}") FROM "{table}"'
            ).fetchone()[0]
            samples = [row[col_idx] for row in sample_rows]

            col_record: dict[str, Any] = {
                "name": col_name,
                "dtype": declared_types[col_name],
                "null_count": null_count,
                "unique_count": unique_count,
                "sample_values": samples,
            }
            # Only ask for min/max when the declared type smells numeric.
            if any(
                token in declared_types[col_name]
                for token in ("int", "real", "num", "float", "double")
            ):
                row = conn.execute(
                    f'SELECT MIN("{col_name}"), MAX("{col_name}") FROM "{table}"'
                ).fetchone()
                col_record["min"] = row[0]
                col_record["max"] = row[1]
            column_profiles.append(col_record)

    return {
        "path": str(db_path),
        "loader": "sqlite",
        "table": table,
        "row_count": row_count,
        "columns": column_profiles,
    }


# ---------- Top-level dispatch --------------------------------------------


def inspect_data(
    path: Path,
    *,
    table: str | None = None,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
) -> dict[str, Any]:
    """Return a one-shot column-level profile of ``path``.

    Format dispatched by extension. ``table`` is required (and only used)
    for sqlite/db inputs.
    """

    if sample_size < 0:
        raise InspectDataError(f"sample_size must be >= 0, got {sample_size}.")

    suffix = path.suffix.lower()
    if suffix in {".sqlite", ".db", ".sqlite3"}:
        if not table:
            raise InspectDataError(
                f"sqlite path {path.name!r} requires a 'table' argument. "
                "Call inspect_sqlite_schema first if you need to discover "
                "table names."
            )
        return _profile_sqlite_table(path, table, sample_size=sample_size)

    if suffix == ".csv":
        column_names, rows = _load_csv_like(path, delimiter=",")
        loader_name = "csv"
    elif suffix == ".tsv":
        column_names, rows = _load_csv_like(path, delimiter="\t")
        loader_name = "tsv"
    elif suffix == ".json":
        column_names, rows = _load_json_records(path)
        loader_name = "json"
    elif suffix in {".jsonl", ".ndjson"}:
        column_names, rows = _load_jsonl(path)
        loader_name = "jsonl"
    else:
        raise InspectDataError(
            f"Unsupported file extension {suffix!r} for inspect_data. "
            "Supported: .csv, .tsv, .json, .jsonl, .ndjson, .sqlite (with table=...)."
        )

    column_profiles = _profile_columns(
        column_names, rows, sample_size=sample_size
    )
    return {
        "path": str(path),
        "loader": loader_name,
        "row_count": len(rows),
        "columns": column_profiles,
    }
