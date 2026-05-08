from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Any, List

class KeyRequest(BaseModel):
    email: EmailStr
    app_name: str
    tier: str = "free"

class TrafficSubmission(BaseModel):
    lat: float
    lon: float
    speed: int
    road_name: Optional[str] = None

class IncidentSubmission(BaseModel):
    lat: float
    lon: float
    category: str
    details: str

class SystemStats(BaseModel):
    status: str
    version: str
    regions: list[str]
    tier: str
    uptime: float

class StandardResponse(BaseModel):
    status: str = "success"
    count: int
    data: Any