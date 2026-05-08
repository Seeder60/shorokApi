"""
source/utils.py — ShorokAPI Core Utilities
===========================================
Connections:
  GISClient   → shorokApi Supabase  (SUPABASE_URL / SUPABASE_KEY)
  OSRM_URL    → routing engine
  ALLOWED_ORIGINS → CORS allowlist

Auth connections (APIBASE_*) live in auth.py — separate Supabase project.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s",
)
logger = logging.getLogger("shorok.utils")

# ─── Environment Validation ───────────────────────────────────────────────────
# APIBASE_MASTERKEY validated here so startup fails fast with a clear message.
# Render env var is MASTER_KEY — we accept both names.
REQUIRED_ENV = ["SUPABASE_URL", "SUPABASE_KEY", "OSRM_URL"]
missing = [e for e in REQUIRED_ENV if not os.getenv(e)]
if missing:
    raise RuntimeError(f"CRITICAL: Missing env vars: {', '.join(missing)}")

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
OSRM_URL:     str = os.getenv("OSRM_URL", "http://router.project-osrm.org").rstrip("/")

# Accept both APIBASE_MASTERKEY and MASTER_KEY (Render uses MASTER_KEY)
APIBASE_MASTERKEY: str = (
    os.getenv("APIBASE_MASTERKEY")
    or os.getenv("MASTER_KEY")
    or "dev-master-key"
)

# ─── CORS Origins ─────────────────────────────────────────────────────────────
# Override in production via ALLOWED_ORIGINS env var (comma-separated).
_default_origins = ",".join([
    "https://shorokapi.dev",
    "https://www.shorokapi.dev",
    "https://shorokapi.onrender.com",
    # python -m http.server 8080
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    # VS Code Live Server
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    # Vite / CRA / Next dev servers
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
])
ALLOWED_ORIGINS: list[str] = os.getenv("ALLOWED_ORIGINS", _default_origins).split(",")


# ─── GIS Client ───────────────────────────────────────────────────────────────
class GISClient:
    """
    Persistent async HTTP client for the shorokApi Supabase project.
    Talks to: SUPABASE_URL (spatial data — roads, railways, traffic, transport)

    Client is initialised once at lifespan startup (main.py) and reused
    for all requests. Do NOT create per-request clients — that leaks sockets.
    """

    def __init__(self):
        # Headers follow Supabase PostgREST auth spec
        self.headers: Dict[str, str] = {
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None
        self.base_url: str = f"{SUPABASE_URL}/rest/v1"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            logger.warning("GISClient: creating fallback httpx client (lifespan not used?)")
            self._client = httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._client

    async def fetch(self, table: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/{table}"
        try:
            r = await self.client.get(url, headers=self.headers, params=params, timeout=8.0)
            r.raise_for_status()
            data = r.json()
            logger.debug("GIS FETCH  table=%-20s  rows=%d", table, len(data) if isinstance(data, list) else 1)
            return data
        except httpx.HTTPStatusError as e:
            logger.error("GIS FETCH HTTP %s  table=%s  body=%s", e.response.status_code, table, e.response.text[:200])
            raise HTTPException(status_code=502, detail=f"Upstream GIS error on {table}: {e.response.status_code}")
        except Exception as e:
            logger.error("GIS FETCH ERROR  table=%s  err=%s", table, str(e))
            raise HTTPException(status_code=502, detail="Upstream GIS engine error")

    async def rpc(self, function_name: str, params: Dict[str, Any]) -> Any:
        url = f"{self.base_url}/rpc/{function_name}"
        try:
            r = await self.client.post(url, headers=self.headers, json=params, timeout=10.0)
            r.raise_for_status()
            data = r.json()
            logger.debug("GIS RPC  fn=%-30s  ok", function_name)
            return data
        except httpx.HTTPStatusError as e:
            logger.error("GIS RPC HTTP %s  fn=%s  body=%s", e.response.status_code, function_name, e.response.text[:200])
            raise HTTPException(status_code=502, detail=f"Geospatial compute failure: {function_name}")
        except Exception as e:
            logger.error("GIS RPC ERROR  fn=%s  err=%s", function_name, str(e))
            raise HTTPException(status_code=502, detail="Geospatial compute failure")

    async def post(self, table: str, data: Dict[str, Any]) -> None:
        url = f"{self.base_url}/{table}"
        try:
            r = await self.client.post(
                url,
                headers={**self.headers, "Prefer": "return=minimal"},
                json=data,
            )
            r.raise_for_status()
            logger.debug("GIS POST  table=%s  ok", table)
        except httpx.HTTPStatusError as e:
            logger.error("GIS POST HTTP %s  table=%s  body=%s", e.response.status_code, table, e.response.text[:200])
            raise HTTPException(status_code=500, detail=f"Failed to write to {table}")
        except Exception as e:
            logger.error("GIS POST ERROR  table=%s  err=%s", table, str(e))
            raise HTTPException(status_code=500, detail="Failed to record spatial data")


# Singleton — imported by spatial.py, system.py, main.py
gis_engine = GISClient()


# ─── Response Helpers ─────────────────────────────────────────────────────────
def standardize_response(data: Any, status: str = "success") -> Dict[str, Any]:
    """Wraps any payload in the standard {status, count, data} envelope."""
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        count = len(data.get("features", []))
    elif isinstance(data, list):
        count = len(data)
    else:
        count = 1 if data else 0

    return {"status": status, "count": count, "data": data}


def to_geojson(data: Any, geom_key: str = "wkt_geometry") -> Dict[str, Any]:
    """
    Converts Supabase rows into a valid GeoJSON FeatureCollection.

    Handles three geometry formats returned by PostGIS/Supabase:
      1. JSON string  → '{"type":"LineString","coordinates":[...]}'
      2. Dict         → already parsed GeoJSON geometry object
      3. WKT string   → 'LINESTRING(90.4 23.8, ...)' — stored as raw string
         in geometry property (Leaflet can't render WKT directly; client must
         parse or use a WKT layer plugin)
    """
    if not isinstance(data, list):
        data = [data] if data else []

    features = []
    for item in data:
        if not isinstance(item, dict):
            continue

        raw_geom = item.get(geom_key)
        geometry = None

        if isinstance(raw_geom, dict):
            # Already a GeoJSON geometry object
            geometry = raw_geom
        elif isinstance(raw_geom, str):
            stripped = raw_geom.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                # JSON-encoded geometry string
                try:
                    geometry = json.loads(stripped)
                except json.JSONDecodeError:
                    logger.warning("to_geojson: failed to parse JSON geometry for item osm_id=%s", item.get("osm_id"))
                    geometry = None
            elif stripped:
                # WKT string — pass through as string; client renders with Leaflet.WKT or similar
                geometry = {"type": "WKT", "wkt": stripped}

        properties = {k: v for k, v in item.items() if k != geom_key}
        features.append({"type": "Feature", "geometry": geometry, "properties": properties})

    return {"type": "FeatureCollection", "features": features}
