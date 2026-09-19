from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ScrapeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Search query or board URL")
    mode: str = Field(default="search", pattern="^(search|board)$")
    limit: int = Field(default=25, ge=1, le=500)
    download: bool = Field(default=True)
    details: bool = Field(default=True)
    dedup: bool = Field(default=False)
    workers: int = Field(default=4, ge=1, le=16)
    delay: float = Field(default=1.0, ge=0, le=30)
    jitter: float = Field(default=0.5, ge=0, le=10)
    batch_size: int = Field(default=10, ge=1, le=100)
    min_width: int = Field(default=0, ge=0)
    min_height: int = Field(default=0, ge=0)
    proxy: str = Field(default="")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "nature photography",
                "mode": "search",
                "limit": 25,
                "download": True,
                "details": True,
                "dedup": False,
                "workers": 4,
                "delay": 1.0,
                "jitter": 0.5,
                "batch_size": 10,
                "min_width": 0,
                "min_height": 0,
                "proxy": "",
            }
        }


class ScrapeResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    phase: str
    progress: int
    total: int
    current: int
    timestamp: str


class PinData(BaseModel):
    id: str
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    thumb: Optional[str] = None
    type: str = "image"
    duration: Optional[int] = None
    created_at: Optional[str] = None


class JobResultResponse(BaseModel):
    status: str
    job_id: str
    pins: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {}
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str


class ErrorResponse(BaseModel):
    detail: str
    status_code: int
    timestamp: str
