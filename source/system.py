"""
source/system.py — Platform health & version endpoints
=======================================================
No authentication required on any of these routes.
"""

import time

import httpx
from fastapi import APIRouter

from source.models import StandardResponse
from source.utils import OSRM_URL, standardize_response

BOOT_TIME = time.time()
VERSION   = "2.3.0"

router = APIRouter(tags=["Platform Management"])


@router.get("/", summary="Portal Welcome", response_model=StandardResponse)
async def root():
    return standardize_response({
        "message": "Welcome to ShorokAPI Bangladesh Developer Portal",
        "docs":    "/portal",
        "status":  "operational",
        "version": VERSION,
    })


@router.get("/health", summary="System Health Check", response_model=StandardResponse)
async def health():
    """Lightweight liveness probe for Render / Cloudflare health checks."""
    return standardize_response({"status": "healthy", "timestamp": time.time()})


@router.get("/status", summary="Detailed System Status", response_model=StandardResponse)
async def get_status():
    """Diagnostic info: uptime, routing engine status, environment."""
    routing_status = "unknown"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{OSRM_URL}/nearest/v1/driving/90.41,23.81")
            routing_status = "online" if res.status_code == 200 else "degraded"
    except Exception:
        routing_status = "offline"

    return standardize_response({
        "uptime_seconds": round(time.time() - BOOT_TIME, 2),
        "routing_engine": routing_status,
        "environment":    "production",
        "region":         "BGD-1",
        "version":        VERSION,
    })


@router.get("/version", summary="API Version Info", response_model=StandardResponse)
async def get_version():
    return standardize_response({
        "version":       VERSION,
        "major":         2,
        "minor":         3,
        "patch":         0,
        "release_stage": "stable",
    })
