"""
ShorokAPI Identity & Access Management
=======================================
Auth uses ONLY X-API-Key. X-API-ID has been removed entirely.

Dependency graph:
  api_key_dep   — all spatial/data endpoints
  admin_key_dep — /v1/keys/generate (master key)
"""

from __future__ import annotations
import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from source.models import KeyRequest

logger = logging.getLogger("shorok.auth")

load_dotenv()

APIBASE_URL:       str = os.getenv("APIBASE_URL", "").rstrip("/")
APIBASE_KEY:       str = os.getenv("APIBASE_KEY", "")
APIBASE_MASTERKEY: str = os.getenv("APIBASE_MASTERKEY", "dev-master-key")

TIER_LIMITS: dict[str, int] = {
    "free":     1_000,
    "standard": 10_000,
    "pro":      1_000_000,
}


class AuthClient:
    """Async client for the Platform Management (apibase) database."""

    def __init__(self):
        self.headers = {
            "apikey":        APIBASE_KEY,
            "Authorization": f"Bearer {APIBASE_KEY}",
            "Content-Type":  "application/json",
        }
        self.base_url = f"{APIBASE_URL}/rest/v1"

    async def get_key_metadata(self, key_hash: str) -> Optional[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.base_url}/api_keys",
                headers=self.headers,
                params={"key_hash": f"eq.{key_hash}", "select": "*"},
            )
            data = r.json()
            return data[0] if data else None

    async def get_usage_count(self, key_hash: str) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.base_url}/api_logs",
                headers={**self.headers, "Prefer": "count=exact", "Range": "0-0"},
                params={"key_hash": f"eq.{key_hash}", "log_date": f"eq.{today}"},
            )
            cr = r.headers.get("Content-Range", "*/0")
            return int(cr.split("/")[-1])

    async def record_analytics(self, key_hash: str, endpoint: str, method: str, status: int):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self.base_url}/api_logs",
                headers=self.headers,
                json={
                    "key_hash":   key_hash,
                    "endpoint":   endpoint,
                    "method":     method,
                    "status_code": status,
                    "log_date":   datetime.now(timezone.utc).date().isoformat(),
                },
            )

    async def create_new_key(self, email: str, app_name: str, tier: str) -> dict[str, Any]:
        raw_token = f"shorok_{secrets.token_urlsafe(32)}"
        khash     = hashlib.sha256(raw_token.encode()).hexdigest()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/api_keys",
                headers={**self.headers, "Prefer": "return=representation"},
                json={
                    "key_hash":    khash,
                    "email":       email,
                    "app_name":    app_name,
                    "tier":        tier,
                    "daily_limit": TIER_LIMITS.get(tier, 1000),
                },
            )
            res = r.json()
            res[0]["raw_key"] = raw_token
            return res[0]


auth_client = AuthClient()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def api_key_dep(
    request: Request,
    x_api_key: str = Header(..., alias="X-API-Key", description="Active ShorokAPI token"),
) -> dict:
    """
    FastAPI dependency — validates X-API-Key on every protected endpoint.

    NOTE: This dependency is intentionally NOT applied to OPTIONS requests.
    CORSPreflightMiddleware in main.py intercepts OPTIONS before routing,
    so this function is never called for preflight — no 422 on missing header.
    """
    if request.method == "OPTIONS":
        # Safety net — should never reach here due to middleware, but guard anyway
        logger.warning("AUTH  OPTIONS reached api_key_dep — middleware misconfigured")
        return {}

    khash    = hash_token(x_api_key)
    metadata = await auth_client.get_key_metadata(khash)

    if not metadata or not metadata.get("active"):
        logger.warning(
            "AUTH REJECT  invalid/inactive key  hash=%.16s...  path=%s",
            khash, request.url.path,
        )
        raise HTTPException(status_code=401, detail="Invalid API key or inactive account")

    used = await auth_client.get_usage_count(khash)
    if used >= metadata["daily_limit"]:
        logger.warning(
            "AUTH RATELIMIT  key=%.16s...  used=%d  limit=%d",
            khash, used, metadata["daily_limit"],
        )
        raise HTTPException(status_code=429, detail="Daily rate limit exceeded")

    await auth_client.record_analytics(khash, request.url.path, request.method, 200)
    logger.debug("AUTH OK  key=%.16s...  path=%s", khash, request.url.path)
    return metadata


async def admin_key_dep(
    x_admin_key: str = Header(..., alias="X-Admin-Key", description="System Master Key"),
):
    if x_admin_key != APIBASE_MASTERKEY:
        logger.warning("ADMIN REJECT  bad master key attempt")
        raise HTTPException(status_code=403, detail="Administrative access required")


# =========================
# KEY MANAGEMENT ROUTER
# =========================
router = APIRouter(prefix="/v1/keys", tags=["Identity & Access"])

@router.post("/generate", dependencies=[Depends(admin_key_dep)])
async def generate(data: KeyRequest):
    """Generate a new API key. Requires X-Admin-Key header."""
    return await auth_client.create_new_key(data.email, data.app_name, data.tier)
