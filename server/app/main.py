import os
import sys
import asyncio
import logging
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.auth import verify_device_credentials, mask_token
from app.websocket_manager import manager
from app.rate_limiter import rate_limiter

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("server.main")

app = FastAPI(
    title=settings.APP_NAME,
    description="Privacy-First Low-Latency Baby Monitor VPS Relay Server",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "baby_online": manager.is_baby_online,
        "parent_count": len(manager.parent_sockets),
        "timestamp": time.time()
    }


@app.get("/api/status")
async def get_system_status(device_id: str, token: str, request: Request):
    client_ip = request.client.host if request.client else "0.0.0.0"
    is_valid, role = verify_device_credentials(device_id, token, client_ip)
    if not is_valid or not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed")
    return {
        "baby_online": manager.is_baby_online,
        "baby_device_id": manager.baby_device_id,
        "baby_last_seen": manager.baby_last_seen,
        "parent_connected_count": len(manager.parent_sockets),
        "role": role
    }


@app.websocket("/ws/stream")
async def websocket_stream_endpoint(
    websocket: WebSocket,
    device_id: str = Query(...),
    token: str = Query(...)
):
    client_ip = websocket.client.host if websocket.client else "0.0.0.0"

    is_valid, role = verify_device_credentials(device_id, token, client_ip)
    if not is_valid or not role:
        logger.warning(f"Rejecting WS from {client_ip} (device_id={device_id})")
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await websocket.accept()
    logger.info(f"[ACCEPTED] {role} device {device_id} from {client_ip}")

    if role == "baby":
        await _handle_baby(websocket, device_id)
    elif role == "parent":
        await _handle_parent(websocket, device_id)


async def _handle_baby(websocket: WebSocket, device_id: str):
    """Baby Client handler: receive audio frames, forward to parents."""
    await manager.register_baby(websocket, device_id)
    try:
        while True:
            try:
                message = await websocket.receive()
            except (WebSocketDisconnect, RuntimeError):
                break

            msg_type = message.get("type", "")
            if msg_type == "websocket.disconnect":
                break
            if msg_type != "websocket.receive":
                continue

            raw_bytes = message.get("bytes")
            raw_text = message.get("text")

            if raw_bytes:
                await manager.forward_audio_frame(websocket, raw_bytes)

            if raw_text:
                try:
                    payload = json.loads(raw_text)
                    if payload.get("type") == "ping":
                        pong = json.dumps({
                            "type": "pong",
                            "client_time": payload.get("time", 0),
                            "server_time": time.time()
                        })
                        await manager.safe_send_text(websocket, pong)
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"[BABY] Error: {e}")
    finally:
        await manager.unregister_baby(websocket)
        logger.info(f"[BABY] {device_id} handler finished")


async def _handle_parent(websocket: WebSocket, device_id: str):
    """
    Parent Client handler: NO receive() loop.
    Parent only RECEIVES audio (sent by forward_audio_frame).
    Disconnect is detected when forward_audio_frame fails to send.
    We send periodic heartbeats to detect dead connections.
    """
    await manager.register_parent(websocket, device_id)
    try:
        # Send initial baby status
        status_msg = json.dumps({
            "type": "status",
            "baby_online": manager.is_baby_online,
            "baby_device_id": manager.baby_device_id,
            "timestamp": time.time()
        })
        await manager.safe_send_text(websocket, status_msg)
        logger.info(f"[PARENT] {device_id} initial status sent, entering keepalive loop")

        # Just send keepalive heartbeats - audio is sent via forward_audio_frame
        # NO websocket.receive() call - this was causing instant disconnects
        while True:
            await asyncio.sleep(10.0)
            heartbeat = json.dumps({
                "type": "heartbeat",
                "server_time": time.time(),
                "baby_online": manager.is_baby_online
            })
            ok = await manager.safe_send_text(websocket, heartbeat)
            if not ok:
                logger.info(f"[PARENT] {device_id} heartbeat failed, connection dead")
                break

    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        logger.info(f"[PARENT] {device_id} disconnected")
    except Exception as e:
        logger.error(f"[PARENT] {device_id} error: {e}")
    finally:
        await manager.unregister_parent(websocket)
        logger.info(f"[PARENT] {device_id} handler finished")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        ws_ping_interval=None,
        ws_ping_timeout=None
    )
