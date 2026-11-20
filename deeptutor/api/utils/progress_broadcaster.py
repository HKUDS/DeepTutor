"""
Progress Broadcaster - Manages WebSocket broadcasting of knowledge base progress
"""

import asyncio
import logging
from typing import Optional
from weakref import WeakValueDictionary

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ProgressBroadcaster:
    """Manages WebSocket broadcasting of knowledge base progress"""

    _instance: Optional["ProgressBroadcaster"] = None
    _connections: dict[str, set[WebSocket]] = {}  # kb_name -> Set[WebSocket]
    _lock = asyncio.Lock()
    _send_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    @classmethod
    def get_instance(cls) -> "ProgressBroadcaster":
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self, kb_name: str, websocket: WebSocket):
        """Connect WebSocket to specified knowledge base"""
        async with self._lock:
            if kb_name not in self._connections:
                self._connections[kb_name] = set()
            self._connections[kb_name].add(websocket)
            logger.debug(
                f"Connected WebSocket for KB '{kb_name}' (total: {len(self._connections[kb_name])})"
            )

    async def disconnect(self, kb_name: str, websocket: WebSocket):
        """Disconnect WebSocket connection"""
        async with self._lock:
            if kb_name in self._connections:
                self._connections[kb_name].discard(websocket)
                if not self._connections[kb_name]:
                    del self._connections[kb_name]
                logger.debug(f"Disconnected WebSocket for KB '{kb_name}'")

    async def broadcast(self, kb_name: str, progress: dict):
        """Broadcast progress update to all WebSocket connections for specified knowledge base"""
        async with self._lock:
            if kb_name not in self._connections:
                return
            connections = tuple(self._connections[kb_name])
            send_lock = self._send_locks.get(kb_name)
            if send_lock is None:
                send_lock = asyncio.Lock()
                self._send_locks[kb_name] = send_lock

        async with send_lock:
            to_remove = []
            for websocket in connections:
                try:
                    await websocket.send_json({"type": "progress", "data": progress})
                except Exception as e:
                    logger.debug(f"Error sending to WebSocket for KB '{kb_name}': {e}")
                    to_remove.append(websocket)

            if to_remove:
                async with self._lock:
                    current = self._connections.get(kb_name)
                    if current is not None:
                        current.difference_update(to_remove)
                        if not current:
                            del self._connections[kb_name]

    def get_connection_count(self, kb_name: str) -> int:
        """Get connection count for specified knowledge base"""
        return len(self._connections.get(kb_name, set()))
