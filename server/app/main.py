import os
import sys
import asyncio
import logging
import json
import time
from typing import Optional

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
    description="Privacy-First Multi-Agent Audio Relay & Monitoring Server by Bash Pro Tech & INTECHA",
    version="2.0.0"
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
    agents = manager.get_agents_list()
    online_count = sum(1 for a in agents if a.get("is_online"))
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "total_agents": len(agents),
        "online_agents": online_count,
        "parent_count": len(manager.parent_sockets),
        "timestamp": time.time()
    }


@app.get("/api/agents")
async def get_agents(device_id: str = Query(...), token: str = Query(...), request: Request = None):
    client_ip = request.client.host if request and request.client else "0.0.0.0"
    is_valid, role = verify_device_credentials(device_id, token, client_ip)
    if not is_valid or not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed")
    return {
        "agents": manager.get_agents_list(),
        "parent_count": len(manager.parent_sockets),
        "timestamp": time.time()
    }


@app.websocket("/ws/stream")
async def websocket_stream_endpoint(
    websocket: WebSocket,
    device_id: str = Query(...),
    token: str = Query(...),
    device_name: Optional[str] = Query(None)
):
    client_ip = websocket.client.host if websocket.client else "0.0.0.0"

    is_valid, role = verify_device_credentials(device_id, token, client_ip)
    if not is_valid or not role:
        logger.warning(f"Rejecting WS from {client_ip} (device_id={device_id})")
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await websocket.accept()
    agent_name = device_name or device_id
    logger.info(f"[ACCEPTED] {role} device '{agent_name}' ({device_id}) from {client_ip}")

    if role == "baby":
        await _handle_agent(websocket, device_id, agent_name)
    elif role == "parent":
        await _handle_parent(websocket, device_id)


async def _handle_agent(websocket: WebSocket, device_id: str, device_name: str):
    """Audio Agent handler: receives continuous PCM audio blocks and forwards to parent."""
    await manager.register_agent(websocket, device_id, device_name)
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
        logger.error(f"[AGENT {device_id}] Error: {e}")
    finally:
        await manager.unregister_agent(websocket)
        logger.info(f"[AGENT {device_id}] handler finished")


async def _handle_parent(websocket: WebSocket, device_id: str):
    """
    Parent Dashboard handler:
    - Receives audio from selected agent
    - Handles incoming selection commands (e.g. switch active agent)
    - Sends periodic heartbeats and agent roster updates
    """
    await manager.register_parent(websocket, device_id)

    async def _incoming_commands():
        try:
            while True:
                message = await websocket.receive()
                msg_type = message.get("type", "")
                if msg_type == "websocket.disconnect":
                    break
                if msg_type != "websocket.receive":
                    continue

                raw_text = message.get("text")
                if raw_text:
                    try:
                        payload = json.loads(raw_text)
                        cmd = payload.get("type")
                        if cmd == "select_agent":
                            target_id = payload.get("agent_id")
                            await manager.set_parent_target_agent(websocket, target_id)
                        elif cmd == "get_agents":
                            await manager.send_agent_list_to_parent(websocket)
                    except Exception as ex:
                        logger.debug(f"Error parsing parent command: {ex}")
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            pass

    async def _heartbeat_loop():
        try:
            while True:
                await asyncio.sleep(8.0)
                heartbeat = json.dumps({
                    "type": "heartbeat",
                    "server_time": time.time(),
                    "agents": manager.get_agents_list()
                })
                ok = await manager.safe_send_text(websocket, heartbeat)
                if not ok:
                    break
        except (asyncio.CancelledError, Exception):
            pass

    cmd_task = asyncio.create_task(_incoming_commands())
    hb_task = asyncio.create_task(_heartbeat_loop())

    try:
        # Wait until one of the tasks finishes (e.g. disconnect)
        done, pending = await asyncio.wait(
            [cmd_task, hb_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
    except Exception as e:
        logger.error(f"[PARENT {device_id}] error: {e}")
    finally:
        cmd_task.cancel()
        hb_task.cancel()
        await manager.unregister_parent(websocket)
        logger.info(f"[PARENT {device_id}] handler finished")


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
