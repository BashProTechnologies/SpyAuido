import asyncio
import logging
import json
import time
import threading
from typing import Callable, Optional, List, Dict
import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK

logger = logging.getLogger("parent.ws_client")


class ParentWebSocketClient:
    """
    Robust Multi-Agent WebSocket Client for Parent / Main Dashboard.
    Receives audio frames from selected agent + real-time roster of all agents.
    """
    def __init__(
        self,
        server_url: str,
        device_id: str,
        device_token: str,
        on_audio_frame: Optional[Callable[[bytes], None]] = None,
        on_status_update: Optional[Callable[[dict], None]] = None,
        on_agent_list_update: Optional[Callable[[List[Dict]], None]] = None,
        on_latency_update: Optional[Callable[[float], None]] = None
    ):
        self.server_url = server_url
        self.device_id = device_id
        self.device_token = device_token
        self.on_audio_frame = on_audio_frame
        self.on_status_update = on_status_update
        self.on_agent_list_update = on_agent_list_update
        self.on_latency_update = on_latency_update

        self.selected_agent_id: Optional[str] = None

        self._ws = None
        self._is_running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        self._initial_backoff = 2.0
        self._max_backoff = 30.0
        self.last_rtt_ms: float = 0.0
        self._frame_count = 0

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._is_running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close_ws(), self._loop)

    def select_agent(self, agent_id: Optional[str]):
        """Command server to route audio from chosen agent ID."""
        self.selected_agent_id = agent_id
        if self._ws and self._loop and self._loop.is_running():
            payload = json.dumps({
                "type": "select_agent",
                "agent_id": agent_id
            })
            asyncio.run_coroutine_threadsafe(self._send_text(payload), self._loop)

    async def _send_text(self, text: str):
        if self._ws:
            try:
                await self._ws.send(text)
            except Exception as e:
                logger.debug(f"Send command failed: {e}")

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main_reconnect_loop())
        except Exception as e:
            logger.error(f"Event loop crashed: {e}")

    async def _close_ws(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _main_reconnect_loop(self):
        backoff = self._initial_backoff

        while self._is_running:
            url_with_auth = f"{self.server_url}?device_id={self.device_id}&token={self.device_token}"

            self._fire_status("connection_state", state="CONNECTING")

            try:
                logger.info(f"Connecting to VPS: {self.server_url}")

                async with websockets.connect(
                    url_with_auth,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=10,
                    max_size=2**20,
                    open_timeout=15
                ) as ws:
                    self._ws = ws
                    self._frame_count = 0
                    backoff = self._initial_backoff
                    logger.info("Connected to VPS Relay Server successfully")

                    self._fire_status("connection_state", state="CONNECTED")

                    # If an agent was previously selected, re-send selection command
                    if self.selected_agent_id:
                        await ws.send(json.dumps({
                            "type": "select_agent",
                            "agent_id": self.selected_agent_id
                        }))

                    await self._receiver_loop(ws)

                logger.info("WebSocket connection closed normally")

            except (ConnectionRefusedError, OSError) as e:
                logger.warning(f"Connection refused: {e}")
            except ConnectionClosed as e:
                logger.warning(f"Connection closed: code={e.code} reason={e.reason}")
            except Exception as e:
                logger.warning(f"Connection error: {type(e).__name__}: {e}")

            self._ws = None
            self._fire_status("connection_state", state="DISCONNECTED",
                              message=f"Retrying in {backoff:.0f}s...")

            if self._is_running:
                await asyncio.sleep(backoff)
                backoff = min(self._max_backoff, backoff * 1.5)

    async def _receiver_loop(self, ws):
        """Receive binary audio frames and JSON agent status updates from server."""
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    # Live PCM Audio frame
                    self._frame_count += 1
                    if self._frame_count == 1:
                        logger.info("First audio frame received from selected agent!")
                    if self.on_audio_frame:
                        self.on_audio_frame(message)

                elif isinstance(message, str):
                    try:
                        payload = json.loads(message)
                        msg_type = payload.get("type")

                        if msg_type in ("agent_list", "heartbeat"):
                            agents = payload.get("agents", [])
                            if self.on_agent_list_update:
                                self.on_agent_list_update(agents)

                        elif msg_type == "status":
                            # Legacy status compatibility
                            baby_online = payload.get("baby_online", False)
                            self._fire_status(
                                "baby_status",
                                baby_online=baby_online,
                                baby_device_id=payload.get("baby_device_id")
                            )

                    except json.JSONDecodeError:
                        pass

        except (ConnectionClosed, ConnectionClosedOK) as e:
            logger.info(f"Receiver closed: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Receiver error: {type(e).__name__}: {e}")

    def _fire_status(self, event_type: str, **kwargs):
        """Safely fire status update callback."""
        if not self.on_status_update:
            return
        event = {"event": event_type}
        event.update(kwargs)
        try:
            self.on_status_update(event)
        except Exception as e:
            logger.error(f"Status callback error: {e}")
