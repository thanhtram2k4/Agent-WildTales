# services/event_bridge.py — Bounded-queue SSE event bridge
"""
Manages SSE subscriber queues with:
- Bounded queue size (prevents memory leaks from slow consumers)
- Graceful disconnect/cleanup
- Thread-safe subscriber management
"""
import asyncio
import json
import logging
import threading
from collections import deque

logger = logging.getLogger("wildtails.event_bridge")

DEFAULT_MAX_QUEUE_SIZE = 100


class EventBridge:
    """Thread-safe event bridge for SSE broadcasting with bounded queues."""

    def __init__(self, max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE):
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()
        self._max_queue_size = max_queue_size
        # Recent events buffer for late-joining clients
        self._recent_events: deque = deque(maxlen=20)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue:
        """Create a new bounded subscriber queue."""
        queue = asyncio.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._subscribers.append(queue)
        logger.info("New SSE subscriber (total: %d)", self.subscriber_count)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue (on disconnect)."""
        with self._lock:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass
        logger.info("SSE subscriber disconnected (remaining: %d)", self.subscriber_count)

    async def broadcast(self, event_payload: dict) -> None:
        """Broadcast an event to all subscribers.

        Drops the event for any subscriber whose queue is full (slow consumer)
        rather than blocking or raising.
        """
        event_json = json.dumps(event_payload)
        self._recent_events.append(event_json)

        with self._lock:
            targets = list(self._subscribers)

        dropped = 0
        for queue in targets:
            try:
                queue.put_nowait(event_json)
            except asyncio.QueueFull:
                dropped += 1
                logger.warning("Dropped event for slow subscriber (queue full)")

        if dropped:
            logger.warning("Dropped events for %d/%d subscribers", dropped, len(targets))

    def get_recent_events(self, n: int = 10) -> list[str]:
        """Return the last n events for late-joining clients."""
        events = list(self._recent_events)
        return events[-n:] if len(events) > n else events


# Module-level singleton
event_bridge = EventBridge()
