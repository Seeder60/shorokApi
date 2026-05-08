from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import List, Dict
import logging
from auth import hash_token, auth_client

logger = logging.getLogger("shorok.ws")
router = APIRouter(prefix="/v1", tags=["Real-time Updates"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.MAX_CONNECTIONS_PER_KEY = 3

    async def connect(self, websocket: WebSocket, key_hash: str):
        # Per-client limit check
        current_conns = [k for k in self.active_connections.keys() if k.startswith(key_hash)]
        if len(current_conns) >= self.MAX_CONNECTIONS_PER_KEY:
            await websocket.close(code=4001, reason="Connection limit exceeded")
            return False
            
        await websocket.accept()
        conn_id = f"{key_hash}_{id(websocket)}"
        self.active_connections[conn_id] = websocket
        return True

    def disconnect(self, websocket: WebSocket, key_hash: str):
        conn_id = f"{key_hash}_{id(websocket)}"
        if conn_id in self.active_connections:
            del self.active_connections[conn_id]

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)

manager = ConnectionManager()

@router.websocket("/live/ws")
async def traffic_websocket(websocket: WebSocket, token: str = Query(...)):
    khash = hash_token(token)
    metadata = await auth_client.get_key_metadata(khash)
    
    if not metadata or not metadata.get("active"):
        await websocket.close(code=4003, reason="Unauthorized")
        return

    if not await manager.connect(websocket, khash):
        return

    try:
        while True:
            # Heartbeat handling / Receive telemetry from clients
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, khash)