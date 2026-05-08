"""
auth.py — ShorokAPI Identity & Access Management
=================================================
Connects to: api(base) Supabase project
  APIBASE_URL  → https://gwaaslvzthwafeymdkcs.supabase.co  (from Render env)
  APIBASE_KEY  → service role / anon key for api(base) project

This is a SEPARATE Supabase project from shorokApi.
  api(base) tables: api_keys, api_logs
  shorokApi tables: roads, railways, traffic_live, transport_points, incidents

Auth uses ONLY X-API-Key. X-API-ID removed entirely.
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

# ─── api(base) Supabase credentials ──────────────────────────────────────────
# Render env vars: APIBASE_URL, APIBASE_KEY, APIBASE_MASTERKEY (or MASTER_KEY)
APIBASE_URL: str = os.getenv("APIBASE_URL", "").rstrip("/")
APIBASE_KEY: str = os.getenv("APIBASE_KEY", "")

# Accept both APIBASE_MASTERKEY and MASTER_KEY (screenshot shows MASTER_KEY in Render)
APIBASE_MASTERKEY: str = (
    os.getenv("APIBASE_MASTERKEY")
    or os.getenv("MASTER_KEY")
    or "dev-master-key"
)

if not APIBASE_URL or not APIBASE_KEY:
    logger.warning(
        "AUTH: APIBASE_URL or APIBASE_KEY not set — "
        "key validation will fail. Set these in Render environment."
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
    Manages api_keys and api_logs tables.

    Uses a single shared httpx.AsyncClient (initialised at lifespan startup)
    instead of a new client per request — avoids socket exhaustion under load.
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

    async def get_key_metadata(self, key_hash: str) -> Optional[dict[str, Any]]:
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

    async def get_usage_count(self, key_hash: str) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            r = await self.client.get(
                f"{self.base_url}/api_logs",
                headers={**self._headers, "Prefer": "count=exact", "Range": "0-0"},
                params={"key_hash": f"eq.{key_hash}", "log_date": f"eq.{today}"},
            )
            r.raise_for_status()
            cr = r.headers.get("Content-Range", "*/0")
            return int(cr.split("/")[-1])
        except Exception as e:
            logger.error("AUTH DB  get_usage_count failed: %s", str(e))
            return 0  # Fail open on count — don't block valid keys if DB hiccups

    async def record_analytics(self, key_hash: str, endpoint: str, method: str, status: int) -> None:
        try:
            r = await self.client.post(
                f"{self.base_url}/api_logs",
                headers={**self._headers, "Prefer": "return=minimal"},
                json={
                    "key_hash":    key_hash,
                    "endpoint":    endpoint,
                    "method":      method,
                    "status_code": status,
                    "log_date":    datetime.now(timezone.utc).date().isoformat(),
                },
            )
            r.raise_for_status()
        except Exception as e:
            # Non-fatal — don't let analytics failures break real requests
            logger.warning("AUTH DB  record_analytics failed (non-fatal): %s", str(e))

    async def create_new_key(self, email: str, app_name: str, tier: str) -> dict[str, Any]:
        raw_token = f"shorok_{secrets.token_urlsafe(32)}"
        khash = hashlib.sha256(raw_token.encode()).hexdigest()
        r = await self.client.post(
            f"{self.base_url}/api_keys",
            headers={**self._headers, "Prefer": "return=representation"},
            json={
                "key_hash":    khash,
                "email":       email,
                "app_name":    app_name,
                "tier":        tier,
                "daily_limit": TIER_LIMITS.get(tier, 1000),
            },
        )
        r.raise_for_status()
        res = r.json()
        res[0]["raw_key"] = raw_token
        logger.info("AUTH  new key created  email=%s  tier=%s", email, tier)
        return res[0]


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
    Validates X-API-Key against the api(base) Supabase project.

    OPTIONS requests are intercepted by CORSPreflightMiddleware in main.py
    before routing — this function is never called for preflight.
    """
    if request.method == "OPTIONS":
        # Safety net only — middleware should prevent reaching here
        logger.warning("AUTH  OPTIONS reached api_key_dep — middleware misconfigured")
        return {}

    khash    = hash_token(x_api_key)
    metadata = await auth_client.get_key_metadata(khash)

    if not metadata or not metadata.get("active"):
        logger.warning("AUTH REJECT  hash=%.16s...  path=%s", khash, request.url.path)
        raise HTTPException(status_code=401, detail="Invalid API key or inactive account")

    used = await auth_client.get_usage_count(khash)
    if used >= metadata["daily_limit"]:
        logger.warning(
            "AUTH RATELIMIT  hash=%.16s...  used=%d  limit=%d",
            khash, used, metadata["daily_limit"],
        )
        raise HTTPException(status_code=429, detail="Daily rate limit exceeded")

    # Fire-and-forget analytics — don't await blocking path
    await auth_client.record_analytics(khash, request.url.path, request.method, 200)
    logger.debug("AUTH OK  hash=%.16s...  path=%s", khash, request.url.path)
    return metadata


async def admin_key_dep(
    x_admin_key: str = Header(..., alias="X-Admin-Key", description="System Master Key"),
) -> None:
    if x_admin_key != APIBASE_MASTERKEY:
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
