"""``query_dataframe``: run SQL over CSV / JSON / JSONL / Parquet files.

Why this exists (data point from 20260506T010810Z run):

* ``execute_python`` was called 121 times across 37 tasks.
* 38 of those calls were the exact pattern ``read_csv(preview)`` →
  ``execute_python(pd.read_csv same file).groupby/merge/value_counts``
  — i.e. "preview the schema, then re-load the whole file in Python to
  do the real aggregation".
* Each such double-read costs one extra LLM round (~30s) plus the prompt
  tokens to ship a custom Python snippet.

This tool collapses that pattern into a single call: it loads the file
into an in-memory sqlite database under the alias ``df`` and executes
the caller's read-only SQL against it. We deliberately use sqlite (not
duckdb) for the SQL backend because:

1. sqlite is in the stdlib — zero new runtime dependency surface for the
   benchmark sandbox to break against;
2. the ``execute_context_sql`` tool already uses sqlite, so the SQL
   dialect agents have learned to use ports over directly;
3. row counts in dabench files are small (a few thousand at most), so
   sqlite's lack of vectorisation is not a perf concern here.

For datasets that genuinely benefit from a vectorised engine (the
benchmark today does not contain any), the agent can still fall back to
``execute_python`` with ``polars`` or ``duckdb`` — both are already
declared dependencies.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

# Reuse the existing read-only SQL gate so we present a single, consistent
# safety contract to the LLM ("only SELECT/WITH/PRAGMA work").
_READ_ONLY_PREFIXES = ("select", "with", "pragma")


# Accepted file extensions and the loader strategy each one uses. Keeping
# this as data (not a long if/elif chain) so adding e.g. ``.tsv`` later is
# a one-line change.
_LOADER_BY_SUFFIX: dict[str, str] = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}


class DataframeQueryError(ValueError):
    """Raised for any user-facing dataframe-query failure.

    We use a dedicated exception class so the LangGraph ``ToolNode``
    surface ``DataframeQueryError: <msg>`` to the LLM, which is easier
    to branch on than a generic ``ValueError``.
    """


def _detect_loader(path: Path) -> str:
    suffix = path.suffix.lower()
    loader = _LOADER_BY_SUFFIX.get(suffix)
    if loader is None:
        raise DataframeQueryError(
            f"Unsupported file extension {suffix!r} for query_dataframe. "
            f"Supported: {sorted(_LOADER_BY_SUFFIX)}. "
            "For sqlite/db files use execute_context_sql instead."
        )
    return loader


def _normalise_columns(raw_columns: list[str]) -> list[str]:
    """Map raw CSV/JSON column names to sqlite-safe identifiers.

    sqlite happily accepts arbitrary quoted identifiers, but the SQL the
    LLM writes will overwhelmingly use bare identifiers. We:

    * preserve the original name as-is when it's already a clean
      identifier (alphanumeric + underscore, doesn't start with a digit);
    * otherwise build a sanitised fallback (replace non-word chars with
      ``_``, prefix a ``c`` if it starts with a digit) and DEDUPLICATE.

    The mapping is reported in the response so the LLM can see what the
    real column names are when its query fails. We intentionally do NOT
    auto-rename columns the LLM already typed correctly — only the
    pathological cases (spaces, dashes, dots) get rewritten.
    """

    seen: set[str] = set()
    normalised: list[str] = []
    for raw in raw_columns:
        candidate = raw if raw and raw[0].isalpha() else f"c_{raw}"
        cleaned_chars = []
        for ch in candidate:
            cleaned_chars.append(ch if (ch.isalnum() or ch == "_") else "_")
        cleaned = "".join(cleaned_chars) or "col"

        # Disambiguate duplicates by suffixing _2, _3, ...
        final = cleaned
        suffix = 2
        while final in seen:
            final = f"{cleaned}_{suffix}"
            suffix += 1
        seen.add(final)
        normalised.append(final)
    return normalised


def _load_csv_like(path: Path, *, delimiter: str) -> tuple[list[str], list[list[Any]]]:
    with path.open(newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _load_json_records(path: Path) -> tuple[list[str], list[list[Any]]]:
    """Load a json file, accepting either a list of records or a dict-of-lists.

    Two shapes are common in dabench:
      1. ``[{"col": v, ...}, ...]`` — list of records (most common)
      2. ``{"col": [v, ...], ...}`` — dict-of-lists (rare but seen in
         narrative-style metadata)

    Anything else (a single dict, a scalar, a deeply nested object) is
    rejected with a clear error rather than silently producing a
    one-row table the LLM cannot reason about.
    """

    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        if not payload:
            return [], []
        if not all(isinstance(item, dict) for item in payload):
            raise DataframeQueryError(
                "JSON list must contain objects (records); "
                "got non-object element."
            )
        # Stable column order = union of keys in first-seen order.
        columns: list[str] = []
        seen_keys: set[str] = set()
        for record in payload:
            for key in record:
                if key not in seen_keys:
                    seen_keys.add(key)
                    columns.append(key)
        rows = [[record.get(col) for col in columns] for record in payload]
        return columns, rows
    if isinstance(payload, dict):
        if not payload:
            return [], []
        if all(isinstance(value, list) for value in payload.values()):
            columns = list(payload.keys())
            length = len(next(iter(payload.values())))
            if not all(len(value) == length for value in payload.values()):
                raise DataframeQueryError(
                    "JSON dict-of-lists has unequal column lengths; "
                    "cannot coerce to a tabular view."
                )
            rows = [[payload[col][idx] for col in columns] for idx in range(length)]
            return columns, rows
    raise DataframeQueryError(
        "Unsupported JSON shape for query_dataframe. Expected either "
        "a list of objects or a dict whose values are equal-length lists. "
        "For nested JSON, use execute_python with json.loads instead."
    )


def _load_jsonl(path: Path) -> tuple[list[str], list[list[Any]]]:
    columns: list[str] = []
    seen_keys: set[str] = set()
    records: list[dict[str, Any]] = []
    with path.open() as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DataframeQueryError(
                    f"JSONL parse error on line {line_no}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise DataframeQueryError(
                    f"JSONL line {line_no} is not a JSON object."
                )
            for key in record:
                if key not in seen_keys:
                    seen_keys.add(key)
                    columns.append(key)
            records.append(record)
    rows = [[record.get(col) for col in columns] for record in records]
    return columns, rows


def _load_parquet(path: Path) -> tuple[list[str], list[list[Any]]]:
    # pyarrow is already a project dependency; importing lazily avoids
    # paying the import cost for the (overwhelmingly common) csv/json
    # path through this tool.
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover — pyarrow is in deps
        raise DataframeQueryError(
            "Parquet support requires pyarrow, which is missing."
        ) from exc

    table = pq.read_table(path.as_posix())
    columns = list(table.schema.names)
    pylist = table.to_pylist()
    rows = [[record.get(col) for col in columns] for record in pylist]
    return columns, rows


def _load_table(path: Path) -> tuple[list[str], list[list[Any]], str]:
    """Dispatch to the right loader, returning (columns, rows, loader_name)."""

    loader = _detect_loader(path)
    if loader == "csv":
        cols, rows = _load_csv_like(path, delimiter=",")
    elif loader == "tsv":
        cols, rows = _load_csv_like(path, delimiter="\t")
    elif loader == "json":
        cols, rows = _load_json_records(path)
    elif loader == "jsonl":
        cols, rows = _load_jsonl(path)
    elif loader == "parquet":
        cols, rows = _load_parquet(path)
    else:  # pragma: no cover — _detect_loader already validated
        raise DataframeQueryError(f"Unhandled loader {loader!r}.")
    return cols, rows, loader


def _validate_read_only(sql: str) -> None:
    stripped = sql.lstrip().lower()
    if not stripped.startswith(_READ_ONLY_PREFIXES):
        raise DataframeQueryError(
            "Only read-only SQL is allowed (SELECT / WITH / PRAGMA). "
            f"Got statement starting with: {stripped[:20]!r}."
        )


def query_dataframe(
    path: Path,
    *,
    sql: str,
    table_alias: str = "df",
    limit: int = 200,
) -> dict[str, Any]:
    """Load ``path`` into an in-memory sqlite table and run ``sql`` against it.

    Pipeline:
        file → in-memory sqlite table named ``table_alias`` (default ``df``)
        → execute ``sql`` (must be SELECT/WITH/PRAGMA) → return up to
        ``limit`` rows + ``column_mapping`` so the LLM can see what
        sqlite-safe names its original columns were renamed to.

    The connection is closed before returning; nothing about the in-memory
    DB persists across calls — this is by design (each call is fully
    deterministic given the same inputs).
    """

    if limit <= 0:
        raise DataframeQueryError(f"limit must be > 0, got {limit}.")
    _validate_read_only(sql)

    raw_columns, raw_rows, loader_name = _load_table(path)
    if not raw_columns:
        return {
            "path": str(path),
            "loader": loader_name,
            "table_alias": table_alias,
            "column_mapping": {},
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
        }

    sqlite_columns = _normalise_columns(raw_columns)
    column_mapping = dict(zip(raw_columns, sqlite_columns, strict=True))

    # Build the in-memory schema with all-TEXT typing — sqlite is
    # dynamically typed and the LLM-facing SQL almost always uses CAST or
    # numeric coercion explicitly when needed. Trying to infer types here
    # adds bug surface (mixed empty strings vs NULLs) for negligible UX win.
    column_decl = ", ".join(f'"{name}"' for name in sqlite_columns)
    insert_placeholders = ", ".join("?" for _ in sqlite_columns)

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(f'CREATE TABLE "{table_alias}" ({column_decl})')
        # csv.reader yields strings already; json/jsonl may yield mixed
        # types — coerce via str() for non-None to keep the all-TEXT
        # storage contract uniform. Empty strings ('') stay '' (not NULL)
        # so the LLM can disambiguate "explicit blank" vs "missing".
        coerced_rows = [
            tuple(None if cell is None else cell if isinstance(cell, (int, float)) else str(cell)
                  for cell in row)
            for row in raw_rows
        ]
        conn.executemany(
            f'INSERT INTO "{table_alias}" VALUES ({insert_placeholders})',
            coerced_rows,
        )
        try:
            cursor = conn.execute(sql)
        except sqlite3.Error as exc:
            raise DataframeQueryError(
                f"SQL execution failed: {exc}. "
                f"Available columns in '{table_alias}': {sqlite_columns}. "
                "If your column names contain spaces/dashes, use the "
                "sanitised names from `column_mapping` in the response."
            ) from exc
        column_names = [item[0] for item in cursor.description or []]
        # fetchmany(limit + 1) lets us detect overflow without paying for
        # an extra query — exactly the same trick execute_context_sql uses.
        fetched = cursor.fetchmany(limit + 1)
    finally:
        conn.close()

    truncated = len(fetched) > limit
    limited_rows = fetched[:limit]
    return {
        "path": str(path),
        "loader": loader_name,
        "table_alias": table_alias,
        "column_mapping": column_mapping,
        "columns": column_names,
        "rows": [list(row) for row in limited_rows],
        "row_count": len(limited_rows),
        "truncated": truncated,
    }
