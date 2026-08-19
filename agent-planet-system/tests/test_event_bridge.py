# tests/test_event_bridge.py — EventBridge bounded queue tests
"""
Tests for:
- Subscribe/unsubscribe lifecycle
- Bounded queue (drops on full)
- Broadcast to multiple subscribers
- Recent events buffer
"""
import asyncio
import pytest
from services.event_bridge import EventBridge


@pytest.fixture
def bridge():
    return EventBridge(max_queue_size=3)


@pytest.mark.asyncio
async def test_subscribe_unsubscribe(bridge):
    """Subscribe adds a queue, unsubscribe removes it."""
    assert bridge.subscriber_count == 0

    q = bridge.subscribe()
    assert bridge.subscriber_count == 1

    bridge.unsubscribe(q)
    assert bridge.subscriber_count == 0


@pytest.mark.asyncio
async def test_broadcast_to_subscribers(bridge):
    """Broadcast should deliver to all subscribers."""
    q1 = bridge.subscribe()
    q2 = bridge.subscribe()

    await bridge.broadcast({"type": "TEST", "data": "hello"})

    msg1 = await q1.get()
    msg2 = await q2.get()
    assert '"TEST"' in msg1
    assert '"TEST"' in msg2


@pytest.mark.asyncio
async def test_bounded_queue_drops_on_full(bridge):
    """When queue is full, broadcast should drop instead of blocking."""
    q = bridge.subscribe()

    # Fill the queue (max_queue_size=3)
    for i in range(3):
        await bridge.broadcast({"i": i})

    # Queue is now full — next broadcast should drop without error
    await bridge.broadcast({"i": 99})

    # Only the first 3 should be in the queue
    assert q.qsize() == 3


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_queue(bridge):
    """Unsubscribing a non-existent queue should not raise."""
    fake_queue = asyncio.Queue()
    bridge.unsubscribe(fake_queue)  # Should not raise


@pytest.mark.asyncio
async def test_recent_events_buffer(bridge):
    """Recent events should be stored for late-joining clients."""
    for i in range(5):
        await bridge.broadcast({"i": i})

    recent = bridge.get_recent_events(n=3)
    assert len(recent) == 3


@pytest.mark.asyncio
async def test_multiple_subscribers_independent(bridge):
    """Each subscriber gets its own copy of events."""
    q1 = bridge.subscribe()
    q2 = bridge.subscribe()

    await bridge.broadcast({"msg": "first"})

    # Consume from q1 only
    await q1.get()

    # q2 should still have its message
    assert not q2.empty()
    msg = await q2.get()
    assert '"first"' in msg
