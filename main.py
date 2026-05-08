import time
import uuid
import httpx
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

from source.utils import gis_engine, ALLOWED_ORIGINS
from auth import router as keys_router
from source.system import router as sys_router
from source.spatial import router as spatial_router
from source.websocket_routes import router as ws_router

logger = logging.getLogger("shorok.main")

# =========================
# OPENAPI METADATA
# =========================
description = """
### ShorokAPI: The Open Transit Intelligence Platform for Bangladesh.

ShorokAPI provides high-performance geospatial data, real-time traffic updates, and public transport routing optimized for the unique infrastructure of Bangladesh.

#### 🔐 Authentication
All requests (except health checks) require an API Key:
- **Standard API Key**: Pass via the `X-API-Key` header.
- **Administrative Key**: Pass via the `X-Admin-Key` header for management endpoints.

#### 🚦 Rate Limiting
Usage is tracked daily based on your subscription tier:
- **Free**: 1,000 requests/day
- **Standard**: 10,000 requests/day
- **Pro**: 1,000,000 requests/day

#### 🛰️ Real-time Updates
Use our WebSocket endpoint at `/v1/live/ws?token={your_key}` for live traffic telemetry streams.

#### 🗺️ Data Standards
- **Spatial Data**: Responses follow the GeoJSON `Feature` or `FeatureCollection` format.
- **Geometry**: EPSG:4326 (WGS 84) coordinate system.
"""

tags_metadata = [
    {"name": "Platform Management", "description": "Core system status and health monitoring."},
    {"name": "Identity & Access", "description": "API key generation and usage analytics."},
    {"name": "Spatial Intelligence", "description": "Road network queries, reverse geocoding, and GIS lookups."},
    {"name": "Traffic & Incidents", "description": "Crowdsourced reports and live road conditions."},
    {"name": "Transit & Logistics", "description": "Bus routes, stops, and fare estimation logic."},
    {"name": "Routing Engine", "description": "Point-to-point directions powered by OSRM."},
    {"name": "Real-time Updates", "description": "WebSocket streams for low-latency telemetry."},
]

# =========================
# APP CONFIG
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ShorokAPI Engine starting up...")
    gis_engine._client = httpx.AsyncClient(
        timeout=10.0,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
    )
    yield
    await gis_engine.client.aclose()
    logger.info("ShorokAPI Engine shutting down...")

app = FastAPI(
    title="ShorokAPI Bangladesh",
    lifespan=lifespan,
    description=description,
    version="2.2.0",
    docs_url="/portal",
    redoc_url="/docs",
    openapi_tags=tags_metadata,
    contact={
        "name": "ShorokAPI Support",
        "url": "https://shorokapi.dev/support",
        "email": "dev@shorokapi.dev",
    },
    license_info={
        "name": "GPL-3.0",
        "url": "https://www.gnu.org/licenses/gpl-3.0.html",
    }
)

@app.middleware("http")
async def production_middleware(request: Request, call_next):
    start_time = time.time()
    request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = str(request_id)
    response.headers["X-Process-Time"] = str(time.time() - start_time)
    return response

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization"],
)

# =========================
# ROUTER REGISTRATION
# =========================
app.include_router(sys_router)  # Root, health, status
app.include_router(keys_router)
app.include_router(spatial_router)
app.include_router(ws_router)