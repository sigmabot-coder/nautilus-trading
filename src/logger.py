"""Async logger with bounded queue and overflow detection."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 10_000
OVERFLOW_REPORT_INTERVAL = 5.0  # seconds


@dataclass
class LoggerStats:
    """Tracks logger queue statistics."""
    messages_enqueued: int = 0
    messages_processed: int = 0
    messages_dropped: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_drop(self) -> None:
        with self._lock:
            self.messages_dropped += 1

    def record_enqueue(self) -> None:
        with self._lock:
            self.messages_enqueued += 1

    def record_processed(self) -> None:
        with self._lock:
            self.messages_processed += 1

    def get_and_reset_drops(self) -> int:
        with self._lock:
            drops = self.messages_dropped
            self.messages_dropped = 0
            return drops


class AsyncLogger:
    """
    Async logger that enqueues messages to a bounded buffer.

    When the queue is full, messages are dropped but the drops are tracked
    and periodically reported so they are never silently lost.
    """

    def __init__(
        self,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        handler: Callable[[str], None] | None = None,
    ) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=maxsize)
        self._handler = handler or (lambda msg: logger.info(msg))
        self._stats = LoggerStats()
        self._running = False
        self._consumer_task: asyncio.Task | None = None
        self._overflow_task: asyncio.Task | None = None

    @property
    def stats(self) -> LoggerStats:
        return self._stats

    async def start(self) -> None:
        """Start the consumer and overflow reporter tasks."""
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume())
        self._overflow_task = asyncio.create_task(self._report_overflow())

    async def stop(self) -> None:
        """Gracefully stop the logger, flushing remaining messages."""
        self._running = False
        await self._queue.put(None)
        if self._consumer_task:
            await self._consumer_task
        if self._overflow_task:
            self._overflow_task.cancel()
            try:
                await self._overflow_task
            except asyncio.CancelledError:
                pass
        self._emit_overflow_report()

    def log(self, message: str) -> None:
        """
        Enqueue a log message. Non-blocking.

        If the queue is full the message is dropped and the drop is recorded.
        Drops are periodically reported so they are never silent.
        """
        try:
            self._queue.put_nowait(message)
            self._stats.record_enqueue()
        except asyncio.QueueFull:
            self._stats.record_drop()

    async def _consume(self) -> None:
        """Consumer loop — processes messages from the queue."""
        while True:
            message = await self._queue.get()
            if message is None:
                while not self._queue.empty():
                    msg = self._queue.get_nowait()
                    if msg is not None:
                        self._handler(msg)
                        self._stats.record_processed()
                break
            self._handler(message)
            self._stats.record_processed()

    async def _report_overflow(self) -> None:
        """Periodically report dropped messages."""
        while self._running:
            await asyncio.sleep(OVERFLOW_REPORT_INTERVAL)
            self._emit_overflow_report()

    def _emit_overflow_report(self) -> None:
        drops = self._stats.get_and_reset_drops()
        if drops > 0:
            warning = f"⚠️ Logger overflow: {drops} messages dropped due to buffer full"
            logger.warning(warning)
