"""Tail ``agent.log`` and emit ``log`` events into a :class:`RunEventBus`.

Strategy: poll the file size every ``poll_interval`` seconds; when it
grows, read the new bytes, split on ``\\n`` (carrying any trailing
partial line over to the next iteration), and publish each complete
line. Long lines are sliced into 64 KiB chunks per backend spec §6.4 so
the WebSocket frame stays under the 1 MiB safety budget.

Why polling instead of ``watchfiles``: ``agent.log`` is appended in
small bursts by stdlib ``FileHandler`` (no fsync), so inotify-style
events can lag. A 100 ms poll keeps end-to-end latency low and works
identically on macOS/Linux/Docker.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from data_agent_baseline.web.services.event_bus import RunEventBus

logger = logging.getLogger("data_agent_baseline.web.log_tailer")

# Per-chunk byte budget. 64 KiB × ~16 chunks = 1 MiB, comfortably under
# the WebSocket frame ceiling. Keep this small enough that a 100 MB
# stack trace doesn't produce a single 100 MB JSON payload.
_CHUNK_BYTES = 64 * 1024
_DEFAULT_POLL_INTERVAL_S = 0.1


class LogTailer:
    """Polls one ``agent.log`` file and pushes ``log`` events to the bus."""

    def __init__(
        self,
        *,
        log_path: Path,
        bus: RunEventBus,
        poll_interval: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._log_path = log_path
        self._bus = bus
        self._poll_interval = poll_interval
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._line_id = 0
        self._buffer = b""
        self._offset = 0

    @property
    def log_path(self) -> Path:
        return self._log_path

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name=f"log-tailer:{self._log_path.name}")

    async def stop(self) -> None:
        """Signal stop and drain any remaining bytes already written.

        Called by ``RunManager`` after the agent finishes — we must read
        the final tail of the file so the WS client doesn't miss the
        last few log lines that landed between the last poll and the
        agent's exit.
        """
        self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            except Exception:  # noqa: BLE001 — never crash on teardown
                logger.exception("log_tailer task raised on shutdown: %s", self._log_path)
            self._task = None
        # One last drain after stop, in case the agent flushed something
        # between the last poll and the stop signal.
        await self._drain_once()
        await self._flush_partial_line()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await self._drain_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                continue

    async def _drain_once(self) -> None:
        try:
            if not self._log_path.exists():
                return
            stat = self._log_path.stat()
        except OSError:
            return
        if stat.st_size <= self._offset:
            # File truncated (rotation) → reset and re-read from 0.
            if stat.st_size < self._offset:
                self._offset = 0
                self._buffer = b""
            return
        try:
            with self._log_path.open("rb") as handle:
                handle.seek(self._offset)
                new_bytes = handle.read(stat.st_size - self._offset)
        except OSError:
            return
        self._offset = stat.st_size
        if not new_bytes:
            return
        self._buffer += new_bytes
        # Split on \n; the last element is whatever follows the final
        # newline (possibly partial), which we hold for next round.
        *complete_lines, self._buffer = self._buffer.split(b"\n")
        for raw_line in complete_lines:
            await self._publish_line(raw_line.decode("utf-8", errors="replace"))

    async def _flush_partial_line(self) -> None:
        if self._buffer:
            await self._publish_line(self._buffer.decode("utf-8", errors="replace"))
            self._buffer = b""

    async def _publish_line(self, line: str) -> None:
        self._line_id += 1
        line_id = self._line_id
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        encoded = line.encode("utf-8")
        # Common case: short line → one chunk, chunk_total=1.
        if len(encoded) <= _CHUNK_BYTES:
            await self._bus.publish(
                {
                    "type": "log",
                    "ts": ts,
                    "line_id": line_id,
                    "chunk_index": 0,
                    "chunk_total": 1,
                    "line": line,
                }
            )
            return
        # Long line: slice on byte boundaries, then decode each slice.
        # We slice bytes (not the str) because grapheme width is irrelevant
        # to WS frame size — only byte count matters. ``errors="replace"``
        # ensures a multi-byte char split across slices doesn't crash decode.
        chunks: list[bytes] = [
            encoded[start : start + _CHUNK_BYTES]
            for start in range(0, len(encoded), _CHUNK_BYTES)
        ]
        chunk_total = len(chunks)
        for chunk_index, chunk_bytes in enumerate(chunks):
            await self._bus.publish(
                {
                    "type": "log",
                    "ts": ts,
                    "line_id": line_id,
                    "chunk_index": chunk_index,
                    "chunk_total": chunk_total,
                    "line": chunk_bytes.decode("utf-8", errors="replace"),
                }
            )
