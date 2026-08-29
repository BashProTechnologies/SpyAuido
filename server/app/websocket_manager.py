import asyncio
import time
import json
import logging
from typing import Dict, Optional, List, Any
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger("server.websocket_manager")


class AgentInfo:
    """Represents an audio capture agent device."""
    def __init__(self, device_id: str, device_name: str, ws: Optional[WebSocket] = None):
        self.device_id = device_id
        self.device_name = device_name
        self.ws = ws
        self.is_online = ws is not None
        self.connected_at = time.time() if ws else 0.0
        self.last_seen = time.time() if ws else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "is_online": self.is_online,
            "last_seen": self.last_seen,
            "connected_at": self.connected_at
        }


class ConnectionManager:
    """
    In-memory real-time Multi-Agent WebSocket router.
    Routes audio from multiple agents to parent dashboards.
    Isolates per-socket errors with per-socket asyncio locks.
    """
    def __init__(self):
        # Known agents map: device_id -> AgentInfo
        self.agents: Dict[str, AgentInfo] = {}
        # WebSocket to device_id mapping for agents
        self.agent_ws_to_id: Dict[WebSocket, str] = {}

        # Parent sockets: ws -> {"device_id": str, "target_agent_id": Optional[str]}
        self.parent_sockets: Dict[WebSocket, Dict[str, Any]] = {}

        self._lock = asyncio.Lock()
        # Per-socket send lock to prevent concurrent write corruption
        self._send_locks: Dict[WebSocket, asyncio.Lock] = {}

    def _get_send_lock(self, ws: WebSocket) -> asyncio.Lock:
        if ws not in self._send_locks:
            self._send_locks[ws] = asyncio.Lock()
        return self._send_locks[ws]

    def _remove_send_lock(self, ws: WebSocket):
        self._send_locks.pop(ws, None)

    async def safe_send_text(self, ws: WebSocket, text: str) -> bool:
        """Thread-safe text send with per-socket locking."""
        try:
            if ws.client_state != WebSocketState.CONNECTED:
                return False
            lock = self._get_send_lock(ws)
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
        try:
            if ws.client_state != WebSocketState.CONNECTED:
                return False
            lock = self._get_send_lock(ws)
            async with lock:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_bytes(data)
                    return True
            return False
        except Exception as e:
            logger.debug(f"safe_send_bytes failed: {e}")
            return False

    async def register_agent(self, websocket: WebSocket, device_id: str, device_name: str):
        """Register or update an active audio agent."""
        async with self._lock:
            # If an older socket exists for this agent ID, close it cleanly
            if device_id in self.agents and self.agents[device_id].ws:
                old_ws = self.agents[device_id].ws
                if old_ws != websocket:
                    logger.warning(f"Replacing existing agent socket for {device_id}")
                    self._remove_send_lock(old_ws)
                    self.agent_ws_to_id.pop(old_ws, None)
                    try:
                        await old_ws.close(code=1000, reason="Replaced by new connection")
                    except Exception:
                        pass

            agent = AgentInfo(device_id=device_id, device_name=device_name, ws=websocket)
            self.agents[device_id] = agent
            self.agent_ws_to_id[websocket] = device_id
            logger.info(f"[ONLINE] Agent connected: '{device_name}' (ID: {device_id})")

        await self.broadcast_agent_list()

    async def unregister_agent(self, websocket: WebSocket):
        """Mark agent as offline when websocket disconnects."""
        device_id = None
        async with self._lock:
            if websocket in self.agent_ws_to_id:
                device_id = self.agent_ws_to_id.pop(websocket)
                self._remove_send_lock(websocket)
                if device_id in self.agents:
                    self.agents[device_id].ws = None
                    self.agents[device_id].is_online = False
                    logger.info(f"[OFFLINE] Agent disconnected: {device_id}")

        if device_id:
            await self.broadcast_agent_list()

    async def register_parent(self, websocket: WebSocket, device_id: str):
        """Register a parent / main dashboard."""
        async with self._lock:
            self.parent_sockets[websocket] = {
                "device_id": device_id,
                "target_agent_id": None  # None = default / first active agent
            }
            logger.info(f"[ONLINE] Parent Dashboard connected: {device_id}")

        # Send initial agent list immediately
        await self.send_agent_list_to_parent(websocket)

    async def unregister_parent(self, websocket: WebSocket):
        """Unregister parent dashboard."""
        async with self._lock:
            if websocket in self.parent_sockets:
                dev_info = self.parent_sockets.pop(websocket)
                self._remove_send_lock(websocket)
                logger.info(f"[OFFLINE] Parent Dashboard disconnected: {dev_info.get('device_id')}")

    async def set_parent_target_agent(self, websocket: WebSocket, target_agent_id: Optional[str]):
        """Set which agent this parent wants to listen to."""
        async with self._lock:
            if websocket in self.parent_sockets:
                self.parent_sockets[websocket]["target_agent_id"] = target_agent_id
                logger.info(f"Parent {self.parent_sockets[websocket]['device_id']} listening to agent: {target_agent_id}")

    def get_agents_list(self) -> List[Dict[str, Any]]:
        """Return list of all known agents with their status."""
        return [agent.to_dict() for agent in self.agents.values()]

    async def send_agent_list_to_parent(self, websocket: WebSocket):
        """Send current agent roster to a specific parent."""
        payload = json.dumps({
            "type": "agent_list",
            "agents": self.get_agents_list(),
            "timestamp": time.time()
        })
        await self.safe_send_text(websocket, payload)

    async def broadcast_agent_list(self):
        """Broadcast updated agent list to all connected parent dashboards."""
        payload = json.dumps({
            "type": "agent_list",
            "agents": self.get_agents_list(),
            "timestamp": time.time()
        })
        disconnected = []
        for ws in list(self.parent_sockets.keys()):
            ok = await self.safe_send_text(ws, payload)
            if not ok:
                disconnected.append(ws)

        for dead_ws in disconnected:
            await self.unregister_parent(dead_ws)

    async def forward_audio_frame(self, sender_socket: WebSocket, data: bytes):
        """Route audio from an agent to parents subscribed to this agent."""
        device_id = self.agent_ws_to_id.get(sender_socket)
        if not device_id:
            return

        if device_id in self.agents:
            self.agents[device_id].last_seen = time.time()

        if not self.parent_sockets:
            return

        disconnected_parents = []
        for parent_ws, parent_meta in list(self.parent_sockets.items()):
            target = parent_meta.get("target_agent_id")
            # If target matches or no specific target is set (single agent default)
            if target == device_id or target is None:
                ok = await self.safe_send_bytes(parent_ws, data)
                if not ok:
                    disconnected_parents.append(parent_ws)

        for dead_ws in disconnected_parents:
            await self.unregister_parent(dead_ws)


manager = ConnectionManager()
