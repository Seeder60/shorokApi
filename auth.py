"""
auth.py — ShorokAPI Identity & Access Management
=================================================
Connects to: api(base) Supabase project
  APIBASE_URL  → https://gwaaslvzthwafeymdkcs.supabase.co  (from Render env)
  APIBASE_KEY  → service role key for api(base) project

This is a SEPARATE Supabase project from shorokApi.
  api(base) tables: api_keys, api_logs
  shorokApi tables: roads, railways, traffic_live, transport_points, incidents

Auth uses ONLY X-API-Key. X-API-ID removed entirely.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from source.models import KeyRequest

logger = logging.getLogger("shorok.auth")

load_dotenv()

# ─── api(base) Supabase credentials ──────────────────────────────────────────
APIBASE_URL: str = os.getenv("APIBASE_URL", "").rstrip("/")
APIBASE_KEY: str = os.getenv("APIBASE_KEY", "")

APIBASE_MASTERKEY: str = os.getenv("APIBASE_MASTERKEY") or os.getenv("MASTER_KEY") or ""

if not APIBASE_URL or not APIBASE_KEY:
    logger.warning(
        "AUTH: APIBASE_URL or APIBASE_KEY not set — "
        "key validation will fail. Set these in Render environment."
    )

if not APIBASE_MASTERKEY:
    raise RuntimeError(
        "CRITICAL: APIBASE_MASTERKEY (or MASTER_KEY) env var is not set. "
        "Set it in Render environment before deploying."
    )

TIER_LIMITS: dict[str, int] = {
    "free":     1_000,
    "standard": 10_000,
    "pro":      1_000_000,
}


# ─── Auth HTTP Client ─────────────────────────────────────────────────────────
class AuthClient:
    """
    Persistent async HTTP client for the api(base) Supabase project.
    Uses a single shared httpx.AsyncClient — avoids socket exhaustion under load.
    """

    def __init__(self):
        self._headers: dict[str, str] = {
            "apikey":        APIBASE_KEY,
            "Authorization": f"Bearer {APIBASE_KEY}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None
        self.base_url: str = f"{APIBASE_URL}/rest/v1"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            logger.warning("AuthClient: creating fallback httpx client")
            self._client = httpx.AsyncClient(
                timeout=8.0,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            )
        return self._client

    async def check_and_log_usage(self, key_hash: str, endpoint: str, method: str) -> dict[str, Any]:
        """
        Single atomic DB call via RPC: validates the key, checks rate limit,
        and logs the request — eliminating the TOCTOU race on concurrent requests.
        """
        try:
            r = await self.client.post(
                f"{self.base_url}/rpc/check_and_log_usage",
                headers=self._headers,
                json={"p_key_hash": key_hash, "p_endpoint": endpoint, "p_method": method},
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("AUTH DB  check_and_log_usage failed: %s", str(e))
            return {"allowed": False, "reason": "db_error"}

    async def get_key_metadata(self, key_hash: str) -> Optional[dict[str, Any]]:
        """Used by WebSocket auth (which bypasses the normal HTTP dependency chain)."""
        try:
            r = await self.client.get(
                f"{self.base_url}/api_keys",
                headers=self._headers,
                params={"key_hash": f"eq.{key_hash}", "select": "*"},
            )
            r.raise_for_status()
            data = r.json()
            return data[0] if data else None
        except Exception as e:
            logger.error("AUTH DB  get_key_metadata failed: %s", str(e))
            return None

    async def create_new_key(self, email: str, app_name: str, tier: str) -> dict[str, Any]:
        if tier not in TIER_LIMITS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier '{tier}'. Must be one of: {list(TIER_LIMITS)}",
            )
        raw_token = f"shorok_{secrets.token_urlsafe(32)}"
        khash = hashlib.sha256(raw_token.encode()).hexdigest()
        try:
            r = await self.client.post(
                f"{self.base_url}/api_keys",
                headers={**self._headers, "Prefer": "return=representation"},
                json={
                    "key_hash":    khash,
                    "email":       email,
                    "app_name":    app_name,
                    "tier":        tier,
                    "daily_limit": TIER_LIMITS[tier],
                },
            )
            r.raise_for_status()
            res = r.json()
            if not res:
                raise HTTPException(status_code=500, detail="Key creation returned empty response")
            res[0]["raw_key"] = raw_token
            logger.info("AUTH  new key created  email=%s  tier=%s", email, tier)
            return res[0]
        except HTTPException:
            raise
        except Exception as e:
            logger.error("AUTH  create_new_key failed: %s", str(e))
            raise HTTPException(status_code=500, detail="Failed to create API key")


# Singleton — imported by websocket_routes.py
auth_client = AuthClient()


# ─── Helpers ──────────────────────────────────────────────────────────────────
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ─── FastAPI Dependencies ─────────────────────────────────────────────────────
async def api_key_dep(
    request: Request,
    x_api_key: str = Header(..., alias="X-API-Key", description="Active ShorokAPI token"),
) -> dict:
    """
    Validates X-API-Key via a single atomic DB call that checks validity,
    enforces rate limits, and logs the request in one transaction.

    OPTIONS requests are intercepted by CORSPreflightMiddleware before routing.
    """
    if request.method == "OPTIONS":
        return {}

    khash = hash_token(x_api_key)
    result = await auth_client.check_and_log_usage(
        khash, str(request.url.path), request.method
    )

    if not result.get("allowed"):
        reason = result.get("reason", "unknown")
        if reason == "rate_limit":
            logger.warning("AUTH RATELIMIT  hash=%.16s...  path=%s", khash, request.url.path)
            raise HTTPException(status_code=429, detail="Daily rate limit exceeded")
        logger.warning("AUTH REJECT  hash=%.16s...  reason=%s  path=%s", khash, reason, request.url.path)
        raise HTTPException(status_code=401, detail="Invalid API key or inactive account")

    logger.debug("AUTH OK  hash=%.16s...  path=%s", khash, request.url.path)
    return result


async def admin_key_dep(
    x_admin_key: str = Header(..., alias="X-Admin-Key", description="System Master Key"),
) -> None:
    if not hmac.compare_digest(x_admin_key, APIBASE_MASTERKEY):
        logger.warning("ADMIN REJECT  bad master key")
        raise HTTPException(status_code=403, detail="Administrative access required")


# ─── Router ───────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/v1/keys", tags=["Identity & Access"])

@router.post("/generate", dependencies=[Depends(admin_key_dep)])
async def generate_key(data: KeyRequest):
    """
    Generate a new API key.
    Requires X-Admin-Key header matching APIBASE_MASTERKEY (or MASTER_KEY) env var.
    """
    return await auth_client.create_new_key(data.email, data.app_name, data.tier)
