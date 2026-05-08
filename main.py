import time
import uuid
import httpx
import logging
from typing import Callable
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
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
All requests (except `/`, `/health`, `/status`, `/version`) require an API Key:
- **Header**: `X-API-Key: <your_token>`

> **Note:** `X-API-ID` has been removed. Use only `X-API-Key`.

#### 🚦 Rate Limiting
- **Free**: 1,000 requests/day
- **Standard**: 10,000 requests/day
- **Pro**: 1,000,000 requests/day

#### 🛰️ Real-time Updates
WebSocket at `/v1/live/ws?token={your_key}` — pass the raw API key as the query param.

#### 🗺️ Data Standards
- Spatial responses follow GeoJSON `FeatureCollection` format.
- Geometry: EPSG:4326 (WGS 84).
"""

tags_metadata = [
    {"name": "Platform Management", "description": "Core system status and health monitoring."},
    {"name": "Identity & Access",   "description": "API key generation and usage analytics."},
    {"name": "Spatial Intelligence","description": "Road network queries, reverse geocoding, and GIS lookups."},
    {"name": "Traffic & Incidents", "description": "Crowdsourced reports and live road conditions."},
    {"name": "Transit & Logistics", "description": "Bus routes, stops, and fare estimation logic."},
    {"name": "Routing Engine",      "description": "Point-to-point directions powered by OSRM."},
    {"name": "Real-time Updates",   "description": "WebSocket streams for low-latency telemetry."},
]

# =========================
# CORS CONSTANTS
# Single source of truth — also used by CORSPreflightMiddleware below.
# =========================
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
CORS_ALLOW_HEADERS = ["X-API-Key", "Content-Type", "Authorization", "apikey", "Accept", "Origin"]

# =========================
# OPTIONS PREFLIGHT MIDDLEWARE
#
# WHY THIS EXISTS:
#   api_key_dep uses Header(...) — a required FastAPI dependency.
#   Browsers NEVER send X-API-Key on OPTIONS preflight by spec.
#   Result without this: FastAPI raises 422 before CORS headers attach.
#   This middleware intercepts OPTIONS first, returns 200 immediately.
#
# REGISTRATION ORDER (Starlette middleware stack is LIFO):
#   add_middleware(GZipMiddleware)          → executes 4th
#   add_middleware(CORSMiddleware)          → executes 3rd
#   @app.middleware production_middleware   → executes 2nd
#   add_middleware(CORSPreflightMiddleware) → executes 1st  ← registered last
# =========================
class CORSPreflightMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        origin = request.headers.get("origin", "")

        if request.method == "OPTIONS":
            logger.debug("PREFLIGHT  origin=%-40s  path=%s", origin or "(none)", request.url.path)

            if origin and origin not in ALLOWED_ORIGINS:
                logger.warning("CORS BLOCK  preflight from unlisted origin: %s  path=%s", origin, request.url.path)
                return Response(status_code=403, content="Origin not allowed")

            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin":      origin or "*",
                    "Access-Control-Allow-Methods":     ", ".join(CORS_ALLOW_METHODS),
                    "Access-Control-Allow-Headers":     ", ".join(CORS_ALLOW_HEADERS),
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Max-Age":           "600",
                },
            )

        response = await call_next(request)

        # Log any request from an origin not in our allowlist (real requests, not OPTIONS)
        if origin and origin not in ALLOWED_ORIGINS:
            logger.warning(
                "CORS WARN   origin not in allowlist: %s  method=%s  path=%s  status=%s",
                origin, request.method, request.url.path, response.status_code
            )

        return response


# =========================
# APP CONFIG
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ShorokAPI starting — origins=%s", ALLOWED_ORIGINS)
    gis_engine._client = httpx.AsyncClient(
        timeout=10.0,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
    )
    yield
    await gis_engine.client.aclose()
    logger.info("ShorokAPI shutting down.")

app = FastAPI(
    title="ShorokAPI Bangladesh",
    lifespan=lifespan,
    description=description,
    version="2.2.0",
    docs_url="/portal",
    redoc_url="/docs",
    openapi_tags=tags_metadata,
    contact={"name": "ShorokAPI Support", "url": "https://shorokapi.dev/support", "email": "dev@shorokapi.dev"},
    license_info={"name": "GPL-3.0", "url": "https://www.gnu.org/licenses/gpl-3.0.html"},
)

# =========================
# MIDDLEWARE — order matters (LIFO execution)
# =========================

# 4th to execute — compress responses
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 3rd to execute — attach CORS headers on real (non-OPTIONS) responses
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,                  # required: browser sends X-API-Key custom header
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=CORS_ALLOW_HEADERS,
    max_age=600,
)

# 2nd to execute — request tracing
@app.middleware("http")
async def production_middleware(request: Request, call_next):
    start_time  = time.time()
    request_id  = str(uuid.uuid4())
    response    = await call_next(request)
    response.headers["X-Request-ID"]   = request_id
    response.headers["X-Process-Time"] = f"{time.time() - start_time:.4f}"
    return response

# 1st to execute — OPTIONS bypass (registered last = runs first in LIFO)
app.add_middleware(CORSPreflightMiddleware)

# =========================
# ROUTER REGISTRATION — always after all middleware
# =========================
app.include_router(sys_router)      # /, /health, /status, /version
app.include_router(keys_router)     # /v1/keys/*
app.include_router(spatial_router)  # /v1/roads, /v1/traffic, etc.
app.include_router(ws_router)       # /v1/live/ws
