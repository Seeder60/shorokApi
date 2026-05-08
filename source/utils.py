import os
import math
import logging
import time
import httpx
import json
from fastapi import HTTPException
from typing import Optional, List, Dict, Any

# Structured Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s"
)
logger = logging.getLogger("shorok.utils")

# 1. Environment Validation
REQUIRED_ENV = ["SUPABASE_URL", "SUPABASE_KEY", "APIBASE_MASTERKEY", "OSRM_URL"]
missing = [env for env in REQUIRED_ENV if not os.getenv(env)]
if missing:
    error_msg = f"CRITICAL: Missing required environment variables: {', '.join(missing)}"
    logger.error(error_msg)
    raise RuntimeError(error_msg)

SUPABASE_URL = os.getenv("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OSRM_URL = os.getenv("OSRM_URL", "http://router.project-osrm.org").rstrip("/")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://shorokapi.dev").split(",")

class GISClient:
    """High-performance singleton for GIS and Auth database communication."""
    def __init__(self):
        self.headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None
        self.base_url = f"{SUPABASE_URL}/rest/v1"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Fallback for non-lifespan contexts, though lifespan is preferred
            self._client = httpx.AsyncClient(timeout=10.0, limits=httpx.Limits(max_connections=100))
        return self._client

    async def fetch(self, table: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            r = await self.client.get(f"{self.base_url}/{table}", headers=self.headers, params=params, timeout=5.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"GIS Fetch Error on {table}: {str(e)}")
            raise HTTPException(status_code=502, detail="Upstream GIS engine error")

    async def rpc(self, function_name: str, params: Dict[str, Any]) -> Any:
        try:
            r = await self.client.post(f"{self.base_url}/rpc/{function_name}", headers=self.headers, json=params, timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"GIS RPC Error on {function_name}: {str(e)}")
            raise HTTPException(status_code=502, detail="Geospatial compute failure")

    async def post(self, table: str, data: Dict[str, Any]):
        try:
            r = await self.client.post(f"{self.base_url}/{table}", headers=self.headers, json=data)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"GIS Post Error on {table}: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to record spatial data")

gis_engine = GISClient()

def standardize_response(data: Any, status: str = "success"):
    """Ensures every response follows the production schema."""
    count = len(data) if isinstance(data, list) else (1 if data else 0)
    # If data is GeoJSON collection, extract count from features
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        count = len(data.get("features", []))
    
    return {
        "status": status,
        "count": count,
        "data": data
    }

def to_geojson(data: Any, geom_key: str = "wkt_geometry") -> Dict[str, Any]:
    """Converts database records into valid GeoJSON FeatureCollection."""
    if not isinstance(data, list):
        data = [data] if data else []
        
    features = []
    for item in data:
        geometry = item.get(geom_key)
        # Handle stringified JSON from PostGIS/Supabase
        if isinstance(geometry, str) and (geometry.startswith('{') or geometry.startswith('[')):
            try:
                geometry = json.loads(geometry)
            except: pass
            
        feat = {
            "type": "Feature",
            "properties": {k: v for k, v in item.items() if k != geom_key},
            "geometry": geometry
        }
        features.append(feat)
    return {"type": "FeatureCollection", "features": features}