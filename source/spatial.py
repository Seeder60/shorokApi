"""
source/spatial.py — ShorokAPI Spatial & Data Endpoints
=======================================================
All endpoints query the shorokApi Supabase project via GISClient (utils.py).
All endpoints require X-API-Key (validated against api(base) Supabase via auth.py).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import api_key_dep
from source.models import IncidentSubmission, StandardResponse
from source.utils import gis_engine, standardize_response, to_geojson

router = APIRouter(prefix="/v1", tags=["Spatial Intelligence"])


# ─── Roads ────────────────────────────────────────────────────────────────────
@router.get("/roads", summary="List road network segments", response_model=StandardResponse)
async def get_roads(
    fclass: Optional[str] = Query(None, description="OSM functional class filter, e.g. 'primary'"),
    name:   Optional[str] = Query(None, description="Partial road name search"),
    limit:  int           = Query(100, le=500),
    offset: int           = Query(0, ge=0),
    _key:   dict          = Depends(api_key_dep),
):
    params: dict = {"select": "osm_id,fclass,name,wkt_geometry", "limit": limit, "offset": offset}
    if fclass:
        params["fclass"] = f"eq.{fclass}"
    if name:
        params["name"] = f"ilike.*{name}*"
    data = await gis_engine.fetch("roads", params)
    return standardize_response(to_geojson(data, "wkt_geometry"))


@router.get("/roads/nearby", summary="Find roads near coordinates", response_model=StandardResponse)
async def get_roads_nearby(
    lat:    float = Query(..., description="Latitude (WGS84)"),
    lon:    float = Query(..., description="Longitude (WGS84)"),
    radius: int   = Query(500, description="Search radius in meters"),
    _key:   dict  = Depends(api_key_dep),
):
    data = await gis_engine.rpc("get_nearby_roads", {"lat": lat, "lon": lon, "radius_meters": radius})
    return standardize_response(to_geojson(data, "wkt_geometry"))


# ─── Railways ─────────────────────────────────────────────────────────────────
@router.get("/railways", summary="List railway network segments", response_model=StandardResponse)
async def get_railways(
    limit: int  = Query(100, le=500),
    _key:  dict = Depends(api_key_dep),
):
    params = {"select": "osm_id,fclass,name,wkt_geometry", "limit": limit}
    data = await gis_engine.fetch("railways", params)
    return standardize_response(to_geojson(data, "wkt_geometry"))


# ─── Search ───────────────────────────────────────────────────────────────────
@router.get("/search", summary="Global spatial search", response_model=StandardResponse)
async def search_spatial(
    q:     str  = Query(..., description="Search term"),
    limit: int  = Query(10, le=100),
    _key:  dict = Depends(api_key_dep),
):
    params = {"select": "osm_id,fclass,name,wkt_geometry", "name": f"ilike.*{q}*", "limit": limit}
    data = await gis_engine.fetch("roads", params)
    return standardize_response(to_geojson(data, "wkt_geometry"))


# ─── Geocoding ────────────────────────────────────────────────────────────────
@router.get("/geocode/reverse", summary="Reverse geocode coordinates", response_model=StandardResponse)
async def reverse_geocode(
    lat:  float = Query(...),
    lon:  float = Query(...),
    _key: dict  = Depends(api_key_dep),
):
    data = await gis_engine.rpc("reverse_geocode", {"lat": lat, "lon": lon})
    return standardize_response(data)


# ─── Traffic ──────────────────────────────────────────────────────────────────
@router.get("/traffic", tags=["Traffic & Incidents"], summary="Live traffic segments", response_model=StandardResponse)
async def get_traffic_status(
    bbox:  Optional[str] = Query(None, description="Bounding box: minLon,minLat,maxLon,maxLat"),
    limit: int           = Query(100, le=500),
    _key:  dict          = Depends(api_key_dep),
):
    params: dict = {"select": "id,osm_id,congestion_level,geometry,updated_at", "limit": limit}
    # TODO: add bbox filtering via PostGIS ST_MakeEnvelope RPC when available
    data = await gis_engine.fetch("traffic_live", params)
    return standardize_response(to_geojson(data, "geometry"))


@router.post("/traffic/report", tags=["Traffic & Incidents"], summary="Submit incident report")
async def report_incident(
    report: IncidentSubmission,
    _key:   dict = Depends(api_key_dep),
):
    await gis_engine.post("incidents", report.model_dump())
    return standardize_response({"message": "Report submitted successfully"})


# ─── Transport ────────────────────────────────────────────────────────────────
@router.get("/transport/stations", tags=["Transit & Logistics"], summary="List transport stations")
async def get_stations(
    station_type: Optional[str] = Query("bus", alias="type", description="Station type: bus, rail, ferry"),
    limit:        int           = Query(50, le=200),
    _key:         dict          = Depends(api_key_dep),
):
    params: dict = {"limit": limit}
    if station_type:
        params["fclass"] = f"eq.{station_type}"
    data = await gis_engine.fetch("transport_points", params)
    return standardize_response(to_geojson(data, "geometry"))


# ─── Routing ──────────────────────────────────────────────────────────────────
@router.get("/routes", tags=["Routing Engine"], summary="Point-to-point directions")
async def calculate_route(
    start:   str  = Query(..., description="Start coords: lat,lon"),
    end:     str  = Query(..., description="End coords: lat,lon"),
    profile: str  = Query("driving", description="Routing profile: driving, cycling, walking"),
    _key:    dict = Depends(api_key_dep),
):
    # OSRM integration placeholder — extend with actual OSRM call
    return standardize_response({"route": "calculated", "engine": profile, "start": start, "end": end})


# ─── ETA ──────────────────────────────────────────────────────────────────────
@router.get("/eta", tags=["Transit & Logistics"], summary="Next vehicle ETA at station")
async def get_eta(
    station_id: str  = Query(..., description="Station identifier"),
    _key:       dict = Depends(api_key_dep),
):
    return standardize_response({"station_id": station_id, "next_arrival_mins": 12})


# ─── Heatmap ──────────────────────────────────────────────────────────────────
@router.get("/heatmap", tags=["Spatial Intelligence"], summary="Congestion density heatmap")
async def get_congestion_heatmap(
    _key: dict = Depends(api_key_dep),
):
    data = await gis_engine.rpc("get_congestion_matrix", {})
    return standardize_response(data)
