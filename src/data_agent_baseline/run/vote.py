"""Cross-round voting for benchmark predictions.

Voting protocol (per task directory):

* Look at the candidate files in priority order:
    ``prediction.csv`` (round 1 / current best), ``r2.csv``, ``r3.csv``,
    and — when ``vote_rounds > 3`` — also ``r4.csv``, ``r5.csv``, ...
* Read each via ``read_prediction_csv``; ``None`` results are dropped.
* If only 0/1/2 of them are non-empty: winner = the first non-empty in
  priority order (always ``prediction.csv`` if it was written, otherwise
  the earliest round that managed to write).
* If 3+ are non-empty: compute their table signatures.
    - If a signature appears with the highest count (>= 2) → winner =
      the EARLIEST file (in priority order) carrying that majority
      signature.
    - If all signatures are distinct (every signature appears exactly
      once) → winner = the EARLIEST file in priority order
      (i.e. ``prediction.csv``, which is round 1's result for the
      end-of-run vote, or the running best for the incremental vote).

If the winner is not already ``prediction.csv``, atomically overwrite
``prediction.csv`` with the winner's bytes. The other rN.csv files are
left in place as trace evidence.

Two entry points:

* :func:`vote_all_tasks` — end-of-run sweep over every ``task_*`` subdir.
  Auto-discovers all ``rN.csv`` candidates so it works for any
  ``vote_rounds`` value, not just 3.
* :func:`vote_task_with_candidates` — single-task incremental vote used
  by the runner after each task completes a round when ``vote_rounds >
  3``. The caller passes the explicit ordered list of candidate
  filenames so the "earliest wins" tiebreaker matches the round order
  the runner actually produced.

A run-level summary is written to ``<run_output_dir>/vote_summary.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from data_agent_baseline.run.table_signature import (
    compute_table_signature,
    read_prediction_csv,
)

# Possible per-candidate file status values surfaced into vote_summary.json.
# Audit-only field added in P5 to make RateLimit / parse-failure impact
# legible in the run summary without changing voting behaviour.
FileStatus = Literal["ok", "missing", "empty", "unparseable"]

# Priority order matters — earlier files win ties and are preferred when no
# majority emerges. ``prediction.csv`` MUST be first (round-1 / fallback /
# running best for incremental voting).
_CANDIDATE_FILENAMES: tuple[str, ...] = ("prediction.csv", "r2.csv", "r3.csv")

# Matches ``r2.csv`` / ``r12.csv`` etc. Used by ``vote_all_tasks`` to
# auto-discover round candidates beyond the default 3.
_ROUND_CSV_PATTERN: re.Pattern[str] = re.compile(r"^r(\d+)\.csv$")


def discover_candidate_filenames(task_dir: Path) -> tuple[str, ...]:
    """Return the ordered list of candidate filenames present in ``task_dir``.

    The order is: ``prediction.csv`` first (always considered, even if
    missing — callers rely on the index-0 slot meaning "the canonical
    file"), then every ``rN.csv`` actually on disk sorted by ``N`` ascending.
    Files that look like ``rfoo.csv`` or ``r0.csv`` are ignored.
    """

    rn_filenames: list[tuple[int, str]] = []
    if task_dir.exists():
        for entry in task_dir.iterdir():
            if not entry.is_file():
                continue
            match = _ROUND_CSV_PATTERN.match(entry.name)
            if not match:
                continue
            round_idx = int(match.group(1))
            if round_idx < 2:  # r0/r1 don't exist by convention
                continue
            rn_filenames.append((round_idx, entry.name))

    rn_filenames.sort(key=lambda pair: pair[0])
    return ("prediction.csv", *(name for _, name in rn_filenames))


@dataclass(frozen=True, slots=True)
class VoteResult:
    """Outcome of voting for a single task directory."""

    task_dir: Path
    winner_filename: str | None       # None = no candidate at all
    winner_overwrote_prediction: bool
    candidate_filenames: tuple[str, ...]
    signatures: tuple[str | None, ...]  # parallel to candidate_filenames; None = unreadable
    rule_applied: str                   # one of: "no_candidates", "single_candidate",
                                        # "two_candidates", "majority", "all_different"
    # P5 audit-only: per-candidate file status, parallel to candidate_filenames.
    # NOT consulted by voting logic — purely observability so the run summary
    # can show which rounds got killed by RateLimit / wrote empty CSV / etc.
    candidate_status: tuple[FileStatus, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_dir": str(self.task_dir),
            "winner_filename": self.winner_filename,
            "winner_overwrote_prediction": self.winner_overwrote_prediction,
            "candidate_filenames": list(self.candidate_filenames),
            "signatures": list(self.signatures),
            "rule_applied": self.rule_applied,
            "candidate_status": list(self.candidate_status),
        }


def _file_status(
    path: Path,
    signature: tuple[tuple[str, ...], ...] | None,
) -> FileStatus:
    """Classify a candidate prediction file for the audit summary.

    Status taxonomy (audit-only — does NOT influence vote winner):
      * ``"missing"``      — file does not exist on disk. Common for rounds
                             that died entirely (e.g. RateLimit at LLM call
                             time, never even reached the writer).
      * ``"empty"``        — file exists but is 0 bytes. Indicates the
                             writer was reached but produced no content.
      * ``"unparseable"``  — file exists and is non-empty, but
                             ``read_prediction_csv`` returned ``None``
                             (signature is None) — CSV malformed, missing
                             header row, etc.
      * ``"ok"``           — file parsed successfully (signature is non-None).

    The caller MUST pass the signature already computed by
    :func:`_signature_for` — this avoids reading each CSV twice and
    guarantees the ``ok`` / ``unparseable`` classification is bit-for-bit
    consistent with what voting actually saw.
    """
    # Signature path is the source of truth: if ``read_prediction_csv``
    # returned a parseable table the signature is non-None and the file is
    # by definition usable. Conversely, signature=None means voting
    # treated this file as absent / corrupted regardless of disk state.
    if signature is not None:
        return "ok"
    if not path.exists():
        return "missing"
    try:
        if path.stat().st_size == 0:
            return "empty"
    except OSError:
        # Symlink loop / permission error — treat as missing for audit.
        return "missing"
    return "unparseable"


def _signature_for(path: Path) -> tuple[tuple[str, ...], ...] | None:
    parsed = read_prediction_csv(path)
    if parsed is None:
        return None
    columns, rows = parsed
    return compute_table_signature(columns, rows)


def _stringify_signature(sig: tuple[tuple[str, ...], ...] | None) -> str | None:
    """Render a signature as a stable, short-ish string for the summary JSON."""
    if sig is None:
        return None
    # Use Python's repr — deterministic and easily diffable. Truncating here
    # would hide collisions; we keep it full-fidelity for debug.
    return repr(sig)


def _atomic_overwrite(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` atomically (write tmp + os.replace)."""
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def vote_task_with_candidates(
    task_dir: Path,
    candidate_filenames: tuple[str, ...],
) -> VoteResult:
    """Apply the voting protocol to one task directory over arbitrary candidates.

    Generalised over the original 3-file protocol so it works for any
    ``vote_rounds`` setting, including the incremental vote that runs
    after every round when ``vote_rounds > 3``.

    Args:
        task_dir: Per-task directory holding ``prediction.csv`` (always at
            index 0 of ``candidate_filenames``) and any ``rN.csv``.
        candidate_filenames: Ordered tuple of candidate filenames. Index 0
            MUST be ``prediction.csv`` (the canonical/winner slot). Earlier
            entries win ties — this is what implements "if all signatures
            differ, pick the first".

    Voting rules:
      * 0 candidates parseable → ``no_candidates``.
      * 1 / 2 candidates parseable → first-present in priority order wins,
        no overwrite (the winner is ``prediction.csv`` whenever round 1
        succeeded; otherwise the round that back-filled it).
      * 3+ candidates parseable:
          * Highest signature count >= 2 → earliest carrier of that
            signature wins (``majority``).
          * Every signature distinct → earliest candidate in priority
            order wins (``all_different``). NOTE: this is candidate index 0
            (= ``prediction.csv``), which for the incremental vote is the
            *running best* from prior rounds, NOT round 1's raw result.
    """

    if not candidate_filenames or candidate_filenames[0] != "prediction.csv":
        raise ValueError(
            "candidate_filenames must be non-empty and start with "
            "'prediction.csv'; got " + repr(candidate_filenames)
        )

    paths = [task_dir / name for name in candidate_filenames]
    signatures = [_signature_for(p) for p in paths]
    string_sigs = tuple(_stringify_signature(s) for s in signatures)
    # P5 audit: per-candidate file status (does NOT influence vote winner —
    # purely observability so the run summary shows which rounds got killed
    # by RateLimit / wrote empty CSV / produced unparseable content).
    # We pass the signature we already computed so _file_status doesn't
    # re-read each CSV; this also guarantees ok/unparseable classification
    # is bit-for-bit consistent with what voting actually saw.
    candidate_status = tuple(
        _file_status(p, sig) for p, sig in zip(paths, signatures, strict=True)
    )

    present_indices = [i for i, sig in enumerate(signatures) if sig is not None]

    if not present_indices:
        return VoteResult(
            task_dir=task_dir,
            winner_filename=None,
            winner_overwrote_prediction=False,
            candidate_filenames=candidate_filenames,
            signatures=string_sigs,
            rule_applied="no_candidates",
            candidate_status=candidate_status,
        )

    if len(present_indices) < 3:
        winner_idx = present_indices[0]
        rule = "single_candidate" if len(present_indices) == 1 else "two_candidates"
        # If the winner is not already at index 0, copy it onto prediction.csv
        # so the canonical slot reflects the only / earliest available answer.
        # This matters for the incremental path: round 4+ may produce the
        # ONLY readable answer when round 1-3 all failed.
        overwrote = False
        if winner_idx != 0 and signatures[0] is None:
            _atomic_overwrite(paths[winner_idx], paths[0])
            overwrote = True
        return VoteResult(
            task_dir=task_dir,
            winner_filename=candidate_filenames[winner_idx],
            winner_overwrote_prediction=overwrote,
            candidate_filenames=candidate_filenames,
            signatures=string_sigs,
            rule_applied=rule,
            candidate_status=candidate_status,
        )

    # 3+ present: count signature occurrences.
    sig_counts: dict[Any, int] = {}
    for sig in signatures:
        if sig is None:
            continue
        sig_counts[sig] = sig_counts.get(sig, 0) + 1
    max_count = max(sig_counts.values())

    if max_count == 1:
        # All distinct → fall back to the earliest present candidate (which
        # is index 0 = prediction.csv whenever it parsed; otherwise the
        # next earliest). User-facing rule: "all results different → take
        # the first one (earliest round)".
        winner_idx = present_indices[0]
        rule = "all_different"
    else:
        majority_sig = next(s for s, c in sig_counts.items() if c == max_count)
        winner_idx = next(
            i for i, s in enumerate(signatures) if s == majority_sig
        )
        rule = "majority"

    overwrote = False
    if winner_idx != 0:
        _atomic_overwrite(paths[winner_idx], paths[0])
        overwrote = True

    return VoteResult(
        task_dir=task_dir,
        winner_filename=candidate_filenames[winner_idx],
        winner_overwrote_prediction=overwrote,
        candidate_filenames=candidate_filenames,
        signatures=string_sigs,
        rule_applied=rule,
    )


def vote_task(task_dir: Path) -> VoteResult:
    """Apply the voting protocol to one task directory.

    Backwards-compatible thin wrapper over
    :func:`vote_task_with_candidates`: auto-discovers all available
    candidates (``prediction.csv`` plus every ``rN.csv`` actually on
    disk), so it now works for any ``vote_rounds`` value, not just 3.
    """

    candidates = discover_candidate_filenames(task_dir)
    return vote_task_with_candidates(task_dir, candidates)


def vote_all_tasks(run_output_dir: Path) -> dict[str, VoteResult]:
    """Run ``vote_task`` over every ``task_*`` subdir; persist a summary.

    Auto-discovers all ``rN.csv`` candidates per task — works for
    arbitrary ``vote_rounds`` (3, 5, 10, ...).
    """

    results: dict[str, VoteResult] = {}
    if not run_output_dir.exists():
        return results

    for entry in sorted(run_output_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Skip dirs with literally nothing votable to keep summary clean.
        candidates = discover_candidate_filenames(entry)
        any_candidate = any((entry / name).exists() for name in candidates)
        if not any_candidate:
            continue
        results[entry.name] = vote_task_with_candidates(entry, candidates)

    summary_path = run_output_dir / "vote_summary.json"
    summary_path.write_text(
        json.dumps(
            {task_id: result.to_dict() for task_id, result in results.items()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return results
