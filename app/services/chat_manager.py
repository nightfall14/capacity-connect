"""Shared native-WebSocket connection manager for the community lounge."""

from __future__ import annotations

from asyncio import Lock

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[int, WebSocket] = {}
        self._lock = Lock()

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        async with self._lock:
            self.active_connections[user_id] = websocket

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for user_id, active_websocket in list(self.active_connections.items()):
                if active_websocket is websocket:
                    del self.active_connections[user_id]

    async def connections_snapshot(self) -> list[WebSocket]:
        async with self._lock:
            return list(self.active_connections.values())

    async def online_user_ids(self) -> list[int]:
        async with self._lock:
            return list(self.active_connections.keys())

    async def send_to_user(self, user_id: int, message: dict) -> bool:
        async with self._lock:
            websocket = self.active_connections.get(user_id)
        if not websocket:
            return False
        try:
            await websocket.send_json(message)
            return True
        except Exception:
            await self.disconnect(websocket)
            return False

    async def broadcast(self, message: dict) -> None:
        sockets = await self.connections_snapshot()
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)

    async def online_count(self) -> int:
        async with self._lock:
            return len(self.active_connections)


manager = ConnectionManager()
