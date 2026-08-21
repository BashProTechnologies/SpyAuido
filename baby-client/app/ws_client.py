import asyncio
import logging
import json
import time
import threading
from typing import Callable, Optional
import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK

logger = logging.getLogger("baby.ws_client")


class WebSocketClient:
    """
    Robust WebSocket Client for Baby PC.
    Sends audio frames as binary, handles pings for keepalive.
    """
    def __init__(
        self,
        server_url: str,
        device_id: str,
        device_token: str,
        on_status_change: Optional[Callable[[str, str], None]] = None
    ):
        self.server_url = server_url
        self.device_id = device_id
        self.device_token = device_token
        self.on_status_change = on_status_change

        self._ws = None
        self._is_running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._send_queue: Optional[asyncio.Queue] = None

        self._initial_backoff = 2.0
        self._max_backoff = 30.0

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

    def send_audio_frame(self, data: bytes):
        if self._loop and self._send_queue and self._is_running:
            try:
                self._loop.call_soon_threadsafe(self._send_queue.put_nowait, data)
            except asyncio.QueueFull:
                pass
            except Exception:
                pass

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
        self._send_queue = asyncio.Queue(maxsize=200)
        backoff = self._initial_backoff

        while self._is_running:
            url_with_auth = f"{self.server_url}?device_id={self.device_id}&token={self.device_token}"

            if self.on_status_change:
                self.on_status_change("CONNECTING", "Connecting to VPS...")

            try:
                logger.info(f"Connecting to {self.server_url}")

                async with websockets.connect(
                    url_with_auth,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=10,
                    max_size=2**20,
                    open_timeout=15
                ) as ws:
                    self._ws = ws
                    backoff = self._initial_backoff
                    logger.info("Connected to VPS Relay Server")

                    if self.on_status_change:
                        self.on_status_change("CONNECTED", "Authenticated & Connected to VPS")

                    # Drain any stale frames from queue
                    while not self._send_queue.empty():
                        try:
                            self._send_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                    # Run sender, receiver, and ping concurrently
                    sender_task = asyncio.create_task(self._sender_loop(ws))
                    ping_task = asyncio.create_task(self._ping_loop(ws))
                    receiver_task = asyncio.create_task(self._receiver_loop(ws))

                    try:
                        # Wait for any to finish (= connection lost)
                        done, pending = await asyncio.wait(
                            [sender_task, ping_task, receiver_task],
                            return_when=asyncio.FIRST_COMPLETED
                        )
                    finally:
                        for task in [sender_task, ping_task, receiver_task]:
                            if not task.done():
                                task.cancel()
                                try:
                                    await task
                                except (asyncio.CancelledError, Exception):
                                    pass

                logger.info("WebSocket connection closed")

            except (ConnectionRefusedError, OSError) as e:
                logger.warning(f"Connection refused: {e}")
            except ConnectionClosed as e:
                logger.warning(f"Connection closed: code={e.code}")
            except Exception as e:
                logger.warning(f"Connection error: {type(e).__name__}: {e}")

            self._ws = None

            if self.on_status_change:
                self.on_status_change("DISCONNECTED", f"Retrying in {backoff:.0f}s...")

            if self._is_running:
                await asyncio.sleep(backoff)
                backoff = min(self._max_backoff, backoff * 1.5)

    async def _sender_loop(self, ws):
        """Drain audio frame queue and send over WebSocket."""
        try:
            while self._is_running:
                try:
                    data = await asyncio.wait_for(self._send_queue.get(), timeout=5.0)
                    await ws.send(data)
                except asyncio.TimeoutError:
                    continue
                except (ConnectionClosed, ConnectionClosedError):
                    break
        except asyncio.CancelledError:
            pass

    async def _ping_loop(self, ws):
        """Send application-level heartbeat ping every 5 seconds."""
        try:
            await asyncio.sleep(1.0)  # Wait before first ping
            while self._is_running:
                try:
                    payload = json.dumps({"type": "ping", "time": time.time()})
                    await ws.send(payload)
                except (ConnectionClosed, ConnectionClosedError):
                    break
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass

    async def _receiver_loop(self, ws):
        """Receive server messages to keep connection alive."""
        try:
            async for msg in ws:
                pass  # Baby just keeps receive loop active
        except (ConnectionClosed, ConnectionClosedOK):
            pass
        except asyncio.CancelledError:
            pass
