from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from data_agent_baseline.benchmark.schema import PublicTask


def resolve_context_path(task: PublicTask, relative_path: str) -> Path:
    candidate = (task.context_dir / relative_path).resolve()
    context_root = task.context_dir.resolve()
    if context_root not in candidate.parents and candidate != context_root:
        raise ValueError(f"Path escapes context dir: {relative_path}")
    if not candidate.exists():
        # Surface a hint listing what does exist so the LLM can self-correct
        # instead of replanning. The vast majority of FileNotFoundError cases
        # are LLMs hallucinating paths (e.g. ``context/data.db`` when the dir
        # only contains JSON files); seeing the real listing in the error
        # message lets the next ``executor`` turn fix the path directly.
        try:
            available = _shallow_listing(context_root)
            hint = f" Available top-level entries under context/: {available}."
        except OSError:  # pragma: no cover — defensive: dir disappeared mid-run
            hint = ""
        raise FileNotFoundError(
            f"Missing context asset: {relative_path}.{hint} "
            f"Tip: call `list_context` first to see the real file layout, "
            f"and pass paths relative to context/ (do NOT prepend 'context/' "
            f"or the task id)."
        )
    return candidate


def _shallow_listing(context_root: Path, *, max_entries: int = 30) -> list[str]:
    """Return up to ``max_entries`` top-level names in ``context_root``.

    Directory entries get a trailing ``/`` so the LLM can tell them apart
    from files at a glance. The list is sorted (dirs first, then files,
    each alphabetical) for determinism across runs.
    """

    children = sorted(
        context_root.iterdir(),
        key=lambda item: (item.is_file(), item.name),
    )
    names: list[str] = []
    for child in children[:max_entries]:
        names.append(f"{child.name}/" if child.is_dir() else child.name)
    if len(children) > max_entries:
        names.append(f"... (+{len(children) - max_entries} more)")
    return names


def glob_files(
    task: PublicTask,
    pattern: str,
    *,
    sort_by: str = "name",
    limit: int = 50,
) -> dict[str, object]:
    """List files under ``context/`` matching a glob ``pattern``.

    Why this exists (data point from 20260506T010810Z run): 7 of 121
    ``execute_python`` calls were wrappers around ``os.listdir`` /
    ``os.walk`` / ``glob.glob`` — usually "find all *.json" or "list the
    db directory". ``list_context`` already exists, but it returns the
    full tree at fixed depth, so the LLM still falls back to Python when
    it wants pattern-based filtering.

    Contract:
    * ``pattern`` is a Python ``Path.glob`` pattern, anchored at
      ``context/``. Use ``**/`` for recursive matches (e.g. ``**/*.json``).
    * ``sort_by`` ∈ {``"name"``, ``"size"``, ``"mtime"``}; results are
      always sorted ascending. Reverse-sort use cases (e.g. "biggest file")
      should sort by size and the LLM can read the last entry.
    * ``limit`` caps the returned list; ``truncated`` flags overflow.
    * Path traversal is blocked: any match resolving outside ``context/``
      (via symlinks etc.) is silently dropped — never raised — so a
      compromised dataset cannot DoS the agent via a single bad glob.
    """

    if sort_by not in {"name", "size", "mtime"}:
        raise ValueError(
            f"glob_files sort_by must be one of name|size|mtime, got {sort_by!r}."
        )
    if limit <= 0:
        raise ValueError(f"glob_files limit must be > 0, got {limit}.")
    # Reject absolute patterns up-front so the LLM cannot accidentally
    # escape via ``glob_files('/etc/*')`` — Path.glob would otherwise
    # treat it as relative-to-anchor on POSIX but the intent is clearly
    # wrong and worth surfacing.
    if pattern.startswith("/"):
        raise ValueError(
            "glob_files pattern must be relative to context/, "
            f"got absolute path {pattern!r}."
        )

    context_root = task.context_dir.resolve()
    matches: list[dict[str, object]] = []
    for candidate in context_root.glob(pattern):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        # Defensive: drop anything that resolves outside context/.
        if context_root != resolved and context_root not in resolved.parents:
            continue
        if not candidate.exists():
            continue
        is_file = candidate.is_file()
        try:
            stat = candidate.stat()
        except OSError:
            continue
        matches.append(
            {
                "path": candidate.relative_to(context_root).as_posix(),
                "kind": "file" if is_file else "dir",
                "size": stat.st_size if is_file else None,
                "mtime": stat.st_mtime,
            }
        )

    if sort_by == "name":
        matches.sort(key=lambda item: str(item["path"]))
    elif sort_by == "size":
        # Dirs (size=None) sort to the end so size-based queries surface
        # files first.
        matches.sort(
            key=lambda item: (item["size"] is None, item["size"] or 0)
        )
    else:  # mtime
        matches.sort(key=lambda item: float(item["mtime"]))

    truncated = len(matches) > limit
    limited = matches[:limit]
    return {
        "root": str(context_root),
        "pattern": pattern,
        "sort_by": sort_by,
        "match_count": len(limited),
        "truncated": truncated,
        "matches": limited,
    }


def list_context_tree(task: PublicTask, *, max_depth: int = 4) -> dict[str, object]:
    entries: list[dict[str, object]] = []

    def walk(path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        for child in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name)):
            rel_path = child.relative_to(task.context_dir).as_posix()
            entries.append(
                {
                    "path": rel_path,
                    "kind": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
            if child.is_dir():
                walk(child, depth + 1)

    walk(task.context_dir, 1)
    return {
        "root": str(task.context_dir),
        "entries": entries,
    }


def read_csv_preview(task: PublicTask, relative_path: str, *, max_rows: int = 50) -> dict[str, object]:
    path = resolve_context_path(task, relative_path)
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    if not rows:
        return {
            "path": relative_path,
            "columns": [],
            "rows": [],
            "row_count": 0,
        }

    header = rows[0]
    data_rows = rows[1:]
    return {
        "path": relative_path,
        "columns": header,
        "rows": data_rows[:max_rows],
        "row_count": len(data_rows),
    }


def read_json_preview(task: PublicTask, relative_path: str, *, max_chars: int = 4000) -> dict[str, object]:
    path = resolve_context_path(task, relative_path)
    payload = json.loads(path.read_text())
    preview = json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "path": relative_path,
        "preview": preview[:max_chars],
        "truncated": len(preview) > max_chars,
    }


# Documents at or below this many characters are returned in full regardless
# of ``max_chars``. Most context docs in the dabench corpus are 5-30 KB; the
# 20260506 retro showed that 5 of 8 step-budget failures (task_352, 355, 379,
# 396, 418) wasted 5-9 turns paginating ~20-30 KB markdown files. Returning
# them in one shot eliminates the pagination cost without bloating context for
# the truly huge cases (multi-hundred-KB patient charts).
SHORT_DOC_FULL_RETURN_THRESHOLD = 32_000

# When ``grep`` is set, hard-cap the number of returned matches so a vague
# pattern (e.g. "the") cannot dump the entire document. 20 windows × 1 KB
# context each ≈ 20 KB worst case, comparable to one paginated read_doc page.
GREP_DEFAULT_MAX_MATCHES = 20

# Per-match context window: characters of surrounding text to include before
# and after the matched span. 400 is wide enough to capture a paragraph in
# typical narrative markdown (publisher card, patient note, etc.).
GREP_DEFAULT_CONTEXT_CHARS = 400


def read_doc_preview(
    task: PublicTask,
    relative_path: str,
    *,
    max_chars: int = 16000,
    offset: int = 0,
    grep: str | None = None,
    max_matches: int = GREP_DEFAULT_MAX_MATCHES,
    context_chars: int = GREP_DEFAULT_CONTEXT_CHARS,
) -> dict[str, object]:
    """Read a text document inside ``context/`` — slice, full, or grep mode.

    Three operating modes (``mode`` in the response makes this explicit):

    * ``"full"`` — Document is short (``total_chars <= SHORT_DOC_FULL_RETURN_THRESHOLD``)
      or the requested ``[offset, offset+max_chars)`` window already covers
      everything. Returns the entire text. ``truncated`` is ``False`` and
      ``next_offset`` is ``None``.
    * ``"slice"`` — Classic pagination path for genuinely long documents.
      ``offset`` is the 0-based starting character index; the returned
      ``preview`` is ``text[offset : offset + max_chars]``. When the slice
      did not consume the full document, ``truncated`` is ``True`` and
      ``next_offset`` points at the next unread character.
    * ``"grep"`` — Activated by passing a non-empty ``grep`` regex. Scans
      the full text, returns up to ``max_matches`` windows of
      ``±context_chars`` around each match, joined by ``\\n---\\n``. Skips
      pagination entirely; ideal when the executor knows the keyword
      (publisher name, patient id, column header, etc.) but not the offset.
      ``matches`` carries per-hit metadata (``start``, ``end``, ``snippet``).

    Why the three modes coexist:

    * The 20260506T010810Z run showed 5/8 failures wasted 5-9 LLM turns
      paginating 20-30 KB docs. ``"full"`` mode below the 32 KB threshold
      collapses those cases to a single tool call.
    * ``task_396`` made 8 ``execute_python`` calls just to grep
      ``superhero.md``; ``"grep"`` mode replaces that with one tool call.
    * The legacy ``"slice"`` mode is preserved verbatim so existing trace
      replays and any explicit ``offset>0`` callers keep working.
    """

    path = resolve_context_path(task, relative_path)
    text = path.read_text(errors="replace")
    total_chars = len(text)

    if offset < 0:
        raise ValueError(f"read_doc offset must be >= 0, got {offset}.")
    if max_chars <= 0:
        raise ValueError(f"read_doc max_chars must be > 0, got {max_chars}.")

    # ---- Grep mode -------------------------------------------------------
    # Active iff caller passed a non-empty pattern. Mutually exclusive with
    # ``offset`` (we ignore offset here — a regex search across the full
    # document is semantically global, partial-document grep is a footgun).
    if grep is not None and grep.strip() != "":
        if max_matches <= 0:
            raise ValueError(f"read_doc max_matches must be > 0, got {max_matches}.")
        if context_chars < 0:
            raise ValueError(
                f"read_doc context_chars must be >= 0, got {context_chars}."
            )
        try:
            pattern = re.compile(grep)
        except re.error as exc:
            raise ValueError(
                f"read_doc grep is not a valid regex: {exc}. "
                "Tip: escape special chars with re.escape semantics, "
                "e.g. use 'Captain Marvel' literally but '\\\\$1.5M' for '$1.5M'."
            ) from exc

        match_records: list[dict[str, object]] = []
        snippets: list[str] = []
        consumed_chars = 0
        for hit in pattern.finditer(text):
            if len(match_records) >= max_matches:
                break
            window_start = max(0, hit.start() - context_chars)
            window_end = min(total_chars, hit.end() + context_chars)
            snippet = text[window_start:window_end]
            # Stop early if we'd blow past max_chars; keep already-collected
            # matches so the caller still gets useful results.
            if consumed_chars + len(snippet) > max_chars and snippets:
                break
            consumed_chars += len(snippet)
            snippets.append(snippet)
            match_records.append(
                {
                    "start": hit.start(),
                    "end": hit.end(),
                    "matched_text": hit.group(0),
                }
            )

        joined = "\n---\n".join(snippets)
        # Truncated here means "more matches existed but max_matches/max_chars
        # cut us off". The next-step suggestion is to refine the pattern, not
        # to paginate.
        more_matches_exist = (
            len(match_records) >= max_matches
            and any(True for _ in pattern.finditer(text[match_records[-1]["end"]:]))
            if match_records
            else False
        )
        return {
            "path": relative_path,
            "mode": "grep",
            "preview": joined,
            "total_chars": total_chars,
            "match_count": len(match_records),
            "matches": match_records,
            "truncated": more_matches_exist,
            "next_offset": None,
            "offset": 0,
            "grep": grep,
        }

    # ---- Full mode -------------------------------------------------------
    # Short docs always return whole; this is the most common shortcut.
    if offset == 0 and total_chars <= SHORT_DOC_FULL_RETURN_THRESHOLD:
        return {
            "path": relative_path,
            "mode": "full",
            "preview": text,
            "offset": 0,
            "next_offset": None,
            "total_chars": total_chars,
            "truncated": False,
        }

    # ---- Slice mode (legacy pagination, unchanged semantics) ------------
    # Clamp offset to the document end so an over-shoot returns an empty
    # slice with truncated=False rather than crashing.
    clamped_offset = min(offset, total_chars)

    end = clamped_offset + max_chars
    preview = text[clamped_offset:end]
    truncated = end < total_chars
    next_offset = end if truncated else None

    # If the single slice already covers the document end, surface that as
    # "full" so the LLM doesn't re-read a now-known-complete file.
    mode = "full" if not truncated and clamped_offset == 0 else "slice"

    return {
        "path": relative_path,
        "mode": mode,
        "preview": preview,
        "offset": clamped_offset,
        "next_offset": next_offset,
        "total_chars": total_chars,
        "truncated": truncated,
    }
