"""Async logger with bounded queue — BUGGY: silently drops messages."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 10_000


class AsyncLogger:
    """Async logger that silently drops messages when queue is full."""

    def __init__(self, maxsize: int = DEFAULT_QUEUE_SIZE, handler=None):
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=maxsize)
        self._handler = handler or (lambda msg: logger.info(msg))
        self._running = False
        self._consumer_task = None

    async def start(self):
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume())

    async def stop(self):
        self._running = False
        await self._queue.put(None)
        if self._consumer_task:
            await self._consumer_task

    def log(self, message: str):
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            pass  # BUG: silently dropped!

    async def _consume(self):
        while True:
            message = await self._queue.get()
            if message is None:
                while not self._queue.empty():
                    msg = self._queue.get_nowait()
                    if msg is not None:
                        self._handler(msg)
                break
            self._handler(message)
