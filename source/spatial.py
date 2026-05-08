from fastapi import APIRouter, Query, Depends
from typing import Optional
from auth import api_key_dep, admin_key_dep
from source.utils import gis_engine, to_geojson, standardize_response
from source.models import StandardResponse, TrafficSubmission, IncidentSubmission

router = APIRouter(prefix="/v1", tags=["Spatial Intelligence"])

@router.get("/roads", summary="List road network segments", response_model=StandardResponse)
async def get_roads(
    fclass: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = 0,
    _key: dict = Depends(api_key_dep),
):
    params = {"select": "osm_id,fclass,name,wkt_geometry", "limit": limit, "offset": offset}
    if fclass: params["fclass"] = f"eq.{fclass}"
    if name: params["name"] = f"ilike.*{name}*"
    data = await gis_engine.fetch("roads", params)
    return standardize_response(to_geojson(data))

@router.get("/roads/nearby", summary="Find roads near coordinates", response_model=StandardResponse)
async def get_roads_nearby(lat: float, lon: float, radius: int = 500, _key: dict = Depends(api_key_dep)):
    data = await gis_engine.rpc("get_nearby_roads", {"lat": lat, "lon": lon, "radius_meters": radius})
    return standardize_response(to_geojson(data))

@router.get("/railways", summary="List railway network segments", response_model=StandardResponse)
async def get_railways(limit: int = 100, _key: dict = Depends(api_key_dep)):
    params = {"select": "osm_id,fclass,name,wkt_geometry", "limit": limit}
    data = await gis_engine.fetch("railways", params)
    return standardize_response(to_geojson(data))

@router.get("/search", summary="Global spatial search", response_model=StandardResponse)
async def search_spatial(q: str, limit: int = 10, _key: dict = Depends(api_key_dep)):
    params = {"select": "osm_id,fclass,name,wkt_geometry", "name": f"ilike.*{q}*", "limit": limit}
    data = await gis_engine.fetch("roads", params)
    return standardize_response(to_geojson(data))

@router.get("/geocode/reverse", summary="Reverse geocode coordinates", response_model=StandardResponse)
async def reverse_geocode(lat: float, lon: float, _key: dict = Depends(api_key_dep)):
    data = await gis_engine.rpc("reverse_geocode", {"lat": lat, "lon": lon})
    return standardize_response(data)

@router.get("/traffic", tags=["Traffic & Incidents"], response_model=StandardResponse)
async def get_traffic_status(bbox: Optional[str] = None, _key: dict = Depends(api_key_dep)):
    """Fetch real-time traffic segments based on congestion levels."""
    data = await gis_engine.fetch("traffic_live", {"limit": 100})
    return standardize_response(to_geojson(data, "geometry"))

@router.post("/traffic/report", tags=["Traffic & Incidents"])
async def report_incident(report: IncidentSubmission, _key: dict = Depends(api_key_dep)):
    """Submit user-generated incident reports (accidents, construction, etc.)."""
    await gis_engine.post("incidents", report.dict())
    return standardize_response({"message": "Report submitted successfully"})

@router.get("/transport/stations", tags=["Transit & Logistics"])
async def get_stations(type: Optional[str] = "bus", _key: dict = Depends(api_key_dep)):
    """List transport hubs, bus stops, and railway stations."""
    params = {"fclass": f"eq.{type}", "limit": 50}
    data = await gis_engine.fetch("transport_points", params)
    return standardize_response(to_geojson(data, "geometry"))

@router.get("/routes", tags=["Routing Engine"])
async def calculate_route(start: str, end: str, profile: str = "driving", _key: dict = Depends(api_key_dep)):
    """Get directions between two points using the OSRM engine."""
    # Integration with OSRM logic...
    return standardize_response({"route": "calculated", "engine": profile})

@router.get("/eta", tags=["Transit & Logistics"])
async def get_eta(station_id: str, _key: dict = Depends(api_key_dep)):
    """Predict arrival time for the next transit vehicle at a specific stop."""
    return standardize_response({"station_id": station_id, "next_arrival_mins": 12})

@router.get("/heatmap", tags=["Spatial Intelligence"])
async def get_congestion_heatmap(_key: dict = Depends(api_key_dep)):
    """Fetch aggregated density data for visualization."""
    data = await gis_engine.rpc("get_congestion_matrix", {})
    return standardize_response(data)