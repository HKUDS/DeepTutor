# -*- coding: utf-8 -*-
"""
Event Bus
=========

Asynchronous event bus for inter-module communication.
Supports publish/subscribe pattern with non-blocking event delivery.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Supported event types."""

    SOLVE_COMPLETE = "SOLVE_COMPLETE"
    QUESTION_COMPLETE = "QUESTION_COMPLETE"


@dataclass
class Event:
    """
    Event data structure for the event bus.

    Attributes:
        type: Event type identifier
        task_id: Unique task identifier
        user_input: Original user input/question
        agent_output: Agent's response/output
        tools_used: List of tools used during the task
        success: Whether the task completed successfully
        metadata: Additional event-specific data
        event_id: Unique event identifier (auto-generated)
        timestamp: Event creation timestamp (auto-generated)
    """

    type: EventType
    task_id: str
    user_input: str
    agent_output: str
    tools_used: List[str] = field(default_factory=list)
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "type": self.type.value if isinstance(self.type, EventType) else self.type,
            "task_id": self.task_id,
            "user_input": self.user_input,
            "agent_output": self.agent_output,
            "tools_used": self.tools_used,
            "success": self.success,
            "metadata": self.metadata,
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
        }


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    Singleton asynchronous event bus.

    Provides publish/subscribe functionality with non-blocking event delivery.
    Events are processed in the background without blocking the publisher.

    Usage:
        # Get the singleton instance
        bus = get_event_bus()

        # Subscribe to events
        async def handle_solve(event: Event):
            print(f"Solve completed: {event.task_id}")

        bus.subscribe(EventType.SOLVE_COMPLETE, handle_solve)

        # Publish events (non-blocking)
        await bus.publish(Event(
            type=EventType.SOLVE_COMPLETE,
            task_id="task-123",
            user_input="What is 2+2?",
            agent_output="The answer is 4.",
        ))
    """

    _instance: Optional["EventBus"] = None
    _initialized: bool = False

    def __new__(cls) -> "EventBus":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # Only initialize once
        if EventBus._initialized:
            return

        self._subscribers: Dict[EventType, List[EventHandler]] = {
            event_type: [] for event_type in EventType
        }
        self._task_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._processor_task: Optional[asyncio.Task] = None
        self._running: bool = False

        EventBus._initialized = True
        logger.debug("EventBus initialized")

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """
        Subscribe a handler to an event type.

        Args:
            event_type: The type of event to subscribe to
            handler: Async function to call when event is published
        """
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)
            logger.debug(f"Handler subscribed to {event_type.value}")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """
        Unsubscribe a handler from an event type.

        Args:
            event_type: The type of event to unsubscribe from
            handler: The handler to remove
        """
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)
            logger.debug(f"Handler unsubscribed from {event_type.value}")

    async def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers (non-blocking).

        The event is queued for background processing, allowing the publisher
        to continue immediately without waiting for handlers to complete.

        Args:
            event: The event to publish
        """
        await self._task_queue.put(event)
        logger.debug(f"Event published: {event.type.value} (task_id={event.task_id})")

        # Start processor if not running
        if not self._running:
            await self.start()

    async def _process_events(self) -> None:
        """Background task that processes queued events."""
        while self._running:
            try:
                # Wait for an event with timeout to allow clean shutdown
                try:
                    event = await asyncio.wait_for(
                        self._task_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Get handlers for this event type
                handlers = self._subscribers.get(event.type, [])

                if not handlers:
                    logger.debug(f"No handlers for event type: {event.type.value}")
                    self._task_queue.task_done()
                    continue

                # Execute all handlers concurrently
                for handler in handlers:
                    try:
                        await handler(event)
                        logger.debug(
                            f"Handler completed for {event.type.value} "
                            f"(task_id={event.task_id})"
                        )
                    except Exception as e:
                        logger.error(
                            f"Handler error for {event.type.value}: {e}",
                            exc_info=True,
                        )

                self._task_queue.task_done()

            except asyncio.CancelledError:
                logger.debug("Event processor cancelled")
                break
            except Exception as e:
                logger.error(f"Event processing error: {e}", exc_info=True)

    async def start(self) -> None:
        """Start the event processor."""
        if self._running:
            return

        self._running = True
        self._processor_task = asyncio.create_task(self._process_events())
        logger.info("EventBus started")

    async def flush(self, timeout: float = 60.0) -> None:
        """Wait for all queued events to be processed without stopping.

        This should be called after publishing events when the caller needs
        to ensure all handlers have completed before continuing (e.g. before
        a blocking ``input()`` call that would freeze the event loop).

        Args:
            timeout: Maximum seconds to wait for the queue to drain.
        """
        if not self._running:
            return
        if self._task_queue.empty():
            return
        logger.debug("EventBus flushing %d pending events...", self._task_queue.qsize())
        try:
            await asyncio.wait_for(self._task_queue.join(), timeout=timeout)
            logger.debug("EventBus flush complete")
        except asyncio.TimeoutError:
            logger.warning(
                "EventBus flush timeout after %.0fs – %d events may still be pending",
                timeout, self._task_queue.qsize(),
            )

    async def stop(self) -> None:
        """Stop the event processor and wait for pending events."""
        if not self._running:
            return

        # First drain the queue while the processor is still running
        try:
            await asyncio.wait_for(self._task_queue.join(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("EventBus shutdown timeout - some events may be lost")

        # Now stop the processor
        self._running = False

        # Cancel processor task
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

        logger.info("EventBus stopped")

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (for testing)."""
        if cls._instance is not None:
            cls._instance._running = False
            if cls._instance._processor_task:
                cls._instance._processor_task.cancel()
        cls._instance = None
        cls._initialized = False


# Module-level singleton accessor
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """
    Get the singleton EventBus instance.

    Returns:
        The global EventBus instance
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus

