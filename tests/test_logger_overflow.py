"""Regression tests for logger message drops under high load.

Verifies that:
1. Drops are detected and counted (never silent)
2. Overflow reports are emitted when drops occur
3. Normal operation has zero drops
"""

import asyncio
import pytest
from src.logger import AsyncLogger


@pytest.mark.asyncio
async def test_no_drops_under_normal_load():
    """Messages are not dropped when queue has capacity."""
    processed = []
    lg = AsyncLogger(maxsize=100, handler=processed.append)
    await lg.start()

    for i in range(50):
        lg.log(f"msg-{i}")

    await asyncio.sleep(0.1)
    await lg.stop()

    assert len(processed) == 50
    assert lg.stats.messages_dropped == 0


@pytest.mark.asyncio
async def test_drops_detected_under_high_load():
    """When queue overflows, drops are counted — never silent."""
    # Use tiny queue and a slow handler to force overflow
    processed = []

    async def slow_handler_sim(msg):
        processed.append(msg)

    lg = AsyncLogger(maxsize=5, handler=lambda msg: processed.append(msg))
    # Do NOT start consumer — messages will pile up and overflow
    # Manually enqueue beyond capacity
    for i in range(20):
        lg.log(f"msg-{i}")

    total_enqueued = lg.stats.messages_enqueued
    total_dropped = lg.stats.messages_dropped

    # Key assertion: every message is accounted for
    assert total_enqueued + total_dropped == 20
    # With maxsize=5, at least 15 should be dropped (queue starts empty, fits 5)
    assert total_dropped >= 15
    assert total_dropped > 0, "Drops must be detected, not silent"


@pytest.mark.asyncio
async def test_overflow_report_emitted(caplog):
    """Overflow report is emitted when drops occur."""
    import logging

    with caplog.at_level(logging.WARNING, logger="src.logger"):
        lg = AsyncLogger(maxsize=2, handler=lambda msg: None)

        # Fill queue beyond capacity
        for i in range(10):
            lg.log(f"msg-{i}")

        assert lg.stats.messages_dropped > 0

        # Trigger the report manually
        lg._emit_overflow_report()

    assert any("messages dropped due to buffer full" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_all_messages_accounted_for():
    """Total enqueued + dropped always equals total attempted."""
    processed = []
    lg = AsyncLogger(maxsize=10, handler=processed.append)

    # Don't start consumer — all messages beyond queue size will be dropped
    attempted = 100
    for i in range(attempted):
        lg.log(f"msg-{i}")

    total = lg.stats.messages_enqueued + lg.stats.messages_dropped
    assert total == attempted, f"Messages unaccounted: {attempted} attempted, {total} tracked"
    # Queue holds 10, rest dropped
    assert lg.stats.messages_enqueued == 10
    assert lg.stats.messages_dropped == 90
