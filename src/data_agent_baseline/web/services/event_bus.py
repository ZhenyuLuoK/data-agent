"""Per-run event bus + monotonic seq numbering.

Each active run owns one :class:`RunEventBus`. Producers
(``LogTailer`` / ``TraceWatcher`` / ``RunManager``) push events; the
WebSocket route is the single consumer. Late-joining clients can replay
from any historical seq because we keep an in-memory ring buffer of
recent events — bounded so a long-running task can't OOM the server.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any


# Hard cap on retained events per run. ~50k entries × 2 KiB ≈ 100 MiB
# worst case, but typical entries are < 500 B so real cost is closer to
# 25 MiB. The trade-off: clients reconnecting after a >50k-event gap
# will only get events from ``min_retained_seq`` onwards (and the WS
# layer must surface that as a snapshot fallback).
_DEFAULT_RING_CAPACITY = 50_000


class RunEventBus:
    """A single-writer, multi-reader fan-out queue.

    Architecture: producers ``await publish(event)`` which assigns a seq
    and broadcasts to every subscribed asyncio.Queue. The ring buffer
    enables ``replay_from(seq)`` for reconnecting clients (spec §6.2).
    """

    def __init__(self, *, ring_capacity: int = _DEFAULT_RING_CAPACITY) -> None:
        self._next_seq = 1
        self._ring: deque[dict[str, Any]] = deque(maxlen=ring_capacity)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._closed = False
        # Lock guards seq assignment + ring append + subscriber fan-out so
        # concurrent producers don't interleave seq numbers.
        self._lock = asyncio.Lock()

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def next_seq(self) -> int:
        return self._next_seq

    async def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        """Assign a seq, archive in the ring, broadcast to subscribers.

        ``event`` is mutated to include ``seq``. Returns the same dict for
        caller convenience (typical pattern: ``await bus.publish({...})``).
        """
        async with self._lock:
            event["seq"] = self._next_seq
            self._next_seq += 1
            self._ring.append(event)
            # Snapshot subscribers under the lock so ``unsubscribe`` during
            # a publish doesn't raise "set changed size during iteration".
            current_subscribers = list(self._subscribers)
        for queue in current_subscribers:
            # Non-blocking put: if a slow client backs up, we drop the
            # oldest entry it hasn't drained yet rather than stall every
            # other consumer. The client can recover via ``?from_seq=N``.
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Discard the head and retry once. Bounded so we never spin.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:  # pragma: no cover — degenerate
                    pass
        return event

    def subscribe(self, *, queue_size: int = 1024) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber and return its private queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def replay_from(self, from_seq: int) -> list[dict[str, Any]]:
        """Return archived events with ``seq >= from_seq``.

        ``from_seq <= 0`` returns the full retained history. If the ring
        has rolled over past ``from_seq``, the caller will see a gap
        (oldest available > requested) and should treat that as a signal
        to send a fresh ``snapshot`` instead.
        """
        if from_seq <= 0:
            return list(self._ring)
        return [event for event in self._ring if event.get("seq", 0) >= from_seq]

    def oldest_retained_seq(self) -> int | None:
        if not self._ring:
            return None
        return int(self._ring[0].get("seq", 0))

    async def close(self) -> None:
        """Mark the bus closed and drop all subscribers.

        Subscribers awaiting on their queue must use a separate
        ``asyncio.wait`` with a stop-event — closing here doesn't
        unblock them by itself.
        """
        self._closed = True
        async with self._lock:
            self._subscribers.clear()
