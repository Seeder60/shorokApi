from pydantic import BaseModel, EmailStr, Field
from typing import Literal, Optional, Any

class KeyRequest(BaseModel):
    email: EmailStr
    app_name: str
    tier: Literal["free", "standard", "pro"] = "free"

class TrafficSubmission(BaseModel):
    lat: float
    lon: float
    speed: int
    road_name: Optional[str] = None

class IncidentSubmission(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
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