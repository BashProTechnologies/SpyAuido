import asyncio
import time
import json
import logging
from typing import Dict, Optional
from fastapi import WebSocket

from starlette.websockets import WebSocketState

logger = logging.getLogger("server.websocket_manager")


class ConnectionManager:
    """
    In-memory real-time WebSocket connection router and audio streaming engine.
    Audio data is routed strictly in RAM with zero disk persistence.
    Uses per-socket send locks to prevent concurrent write corruption.
    """
    def __init__(self):
        self.baby_socket: Optional[WebSocket] = None
        self.baby_device_id: Optional[str] = None
        self.baby_last_seen: float = 0.0

        self.parent_sockets: Dict[WebSocket, str] = {}

        self._lock = asyncio.Lock()
        # Per-socket send lock to prevent concurrent writes
        self._send_locks: Dict[WebSocket, asyncio.Lock] = {}

    @property
    def is_baby_online(self) -> bool:
        return self.baby_socket is not None

    def _get_send_lock(self, ws: WebSocket) -> asyncio.Lock:
        if ws not in self._send_locks:
            self._send_locks[ws] = asyncio.Lock()
        return self._send_locks[ws]

    def _remove_send_lock(self, ws: WebSocket):
        self._send_locks.pop(ws, None)

    async def safe_send_text(self, ws: WebSocket, text: str) -> bool:
        """Thread-safe text send with per-socket locking."""
        if ws.client_state != WebSocketState.CONNECTED:
            return False
        lock = self._get_send_lock(ws)
        try:
            async with lock:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(text)
                    return True
            return False
        except Exception as e:
            logger.debug(f"safe_send_text failed: {e}")
            return False

    async def safe_send_bytes(self, ws: WebSocket, data: bytes) -> bool:
        """Thread-safe binary send with per-socket locking."""
        if ws.client_state != WebSocketState.CONNECTED:
            return False
        lock = self._get_send_lock(ws)
        try:
            async with lock:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_bytes(data)
                    return True
            return False
        except Exception as e:
            logger.debug(f"safe_send_bytes failed: {e}")
            return False

    async def register_baby(self, websocket: WebSocket, device_id: str):
        async with self._lock:
            if self.baby_socket is not None:
                logger.warning(f"Replacing existing Baby Client: {self.baby_device_id}")
                old = self.baby_socket
                self.baby_socket = None
                self._remove_send_lock(old)
                try:
                    await old.close(code=1000, reason="Replaced")
                except Exception:
                    pass

            self.baby_socket = websocket
            self.baby_device_id = device_id
            self.baby_last_seen = time.time()
            logger.info(f"[ONLINE] Baby Client connected: {device_id}")

        await self.broadcast_status_to_parents()

    async def unregister_baby(self, websocket: WebSocket):
        async with self._lock:
            if self.baby_socket == websocket:
                self.baby_socket = None
                self.baby_device_id = None
                self.baby_last_seen = 0.0
                self._remove_send_lock(websocket)
                logger.info("[OFFLINE] Baby Client disconnected.")

        await self.broadcast_status_to_parents()

    async def register_parent(self, websocket: WebSocket, device_id: str):
        async with self._lock:
            self.parent_sockets[websocket] = device_id
            logger.info(f"[ONLINE] Parent Client connected: {device_id}")

    async def unregister_parent(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.parent_sockets:
                dev_id = self.parent_sockets.pop(websocket)
                self._remove_send_lock(websocket)
                logger.info(f"[OFFLINE] Parent Client disconnected: {dev_id}")

    async def send_initial_status_to_parent(self, websocket: WebSocket):
        """Send current baby status to a newly connected parent."""
        status_msg = json.dumps({
            "type": "status",
            "baby_online": self.is_baby_online,
            "baby_device_id": self.baby_device_id,
            "timestamp": time.time()
        })
        await self.safe_send_text(websocket, status_msg)

    async def forward_audio_frame(self, sender_socket: WebSocket, data: bytes):
        if sender_socket != self.baby_socket:
            return

        self.baby_last_seen = time.time()

        if not self.parent_sockets:
            return

        disconnected_parents = []
        for parent_ws in list(self.parent_sockets.keys()):
            ok = await self.safe_send_bytes(parent_ws, data)
            if not ok:
                disconnected_parents.append(parent_ws)

        for dead_ws in disconnected_parents:
            await self.unregister_parent(dead_ws)

    async def broadcast_status_to_parents(self):
        status_msg = json.dumps({
            "type": "status",
            "baby_online": self.is_baby_online,
            "baby_device_id": self.baby_device_id,
            "timestamp": time.time()
        })

        disconnected = []
        for ws in list(self.parent_sockets.keys()):
            ok = await self.safe_send_text(ws, status_msg)
            if not ok:
                disconnected.append(ws)

        for dead_ws in disconnected:
            await self.unregister_parent(dead_ws)


manager = ConnectionManager()
