"""Regression tests for logger message drops under high load.

Verifies that:
1. Drops are detected and counted (never silent)
2. Overflow reports are emitted when drops occur
3. Normal operation has zero drops
"""

import asyncio
import logging
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
    lg = AsyncLogger(maxsize=5, handler=lambda msg: None)
    for i in range(20):
        lg.log(f"msg-{i}")

    assert lg.stats.messages_enqueued + lg.stats.messages_dropped == 20
    assert lg.stats.messages_dropped >= 15
    assert lg.stats.messages_dropped > 0, "Drops must be detected, not silent"


@pytest.mark.asyncio
async def test_overflow_report_emitted(caplog):
    """Overflow report is emitted when drops occur."""
    with caplog.at_level(logging.WARNING, logger="src.logger"):
        lg = AsyncLogger(maxsize=2, handler=lambda msg: None)
        for i in range(10):
            lg.log(f"msg-{i}")
        assert lg.stats.messages_dropped > 0
        lg._emit_overflow_report()

    assert any("messages dropped due to buffer full" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_all_messages_accounted_for():
    """Total enqueued + dropped always equals total attempted."""
    lg = AsyncLogger(maxsize=10, handler=lambda msg: None)
    attempted = 100
    for i in range(attempted):
        lg.log(f"msg-{i}")

    total = lg.stats.messages_enqueued + lg.stats.messages_dropped
    assert total == attempted
    assert lg.stats.messages_enqueued == 10
    assert lg.stats.messages_dropped == 90
