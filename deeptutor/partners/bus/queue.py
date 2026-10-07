"""Async message queue for decoupled channel-agent communication."""

import asyncio
import time

from deeptutor.partners.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels.

        Stamps the enqueue time so the outbound lane can report how long a
        message waited behind other work (the delivery lag a reader sees).
        """
        metadata = msg.metadata
        if isinstance(metadata, dict):
            metadata.setdefault("_enqueued_at", time.monotonic())
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    def try_consume_outbound(self) -> OutboundMessage | None:
        """Return the next queued outbound message without waiting, else ``None``.

        Lets the single partner router look one message ahead (e.g. to merge
        consecutive stream deltas) without blocking or racing another consumer.
        """
        try:
            return self.outbound.get_nowait()
        except asyncio.QueueEmpty:
            return None

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
