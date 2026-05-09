import asyncio
import json
import logging
from typing import Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth import hash_token, auth_client

logger = logging.getLogger("shorok.ws")
router = APIRouter(prefix="/v1", tags=["Real-time Updates"])


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.MAX_CONNECTIONS_PER_KEY = 3

    async def connect(self, websocket: WebSocket, key_hash: str) -> bool:
        current_conns = [k for k in self.active_connections if k.startswith(key_hash)]
        if len(current_conns) >= self.MAX_CONNECTIONS_PER_KEY:
            await websocket.close(code=4001, reason="Connection limit exceeded")
            return False
        conn_id = f"{key_hash}_{id(websocket)}"
        self.active_connections[conn_id] = websocket
        return True

    def disconnect(self, websocket: WebSocket, key_hash: str):
        conn_id = f"{key_hash}_{id(websocket)}"
        self.active_connections.pop(conn_id, None)

    async def broadcast(self, message: dict):
        dead = []
        for conn_id, connection in list(self.active_connections.items()):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(conn_id)
        for conn_id in dead:
            self.active_connections.pop(conn_id, None)


manager = ConnectionManager()


@router.websocket("/live/ws")
async def traffic_websocket(websocket: WebSocket):
    """
    WebSocket endpoint. Auth via first message after connect:
      {"token": "shorok_..."}
    Token is never sent in the URL to avoid leaking it in server/proxy logs.
    """
    await websocket.accept()

    # Expect auth message within 10 seconds
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        msg = json.loads(raw)
        token = msg.get("token", "")
    except asyncio.TimeoutError:
        await websocket.close(code=4003, reason="Authentication timeout")
        return
    except (json.JSONDecodeError, Exception):
        await websocket.close(code=4003, reason="Authentication required")
        return

    if not token:
        await websocket.close(code=4003, reason="Token missing")
        return

    khash = hash_token(token)
    metadata = await auth_client.get_key_metadata(khash)

    if not metadata or not metadata.get("active"):
        await websocket.close(code=4003, reason="Unauthorized")
        return

    if not await manager.connect(websocket, khash):
        return

    logger.info("WS CONNECT  hash=%.16s...", khash)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, khash)
        logger.info("WS DISCONNECT  hash=%.16s...", khash)
