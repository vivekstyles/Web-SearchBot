from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class ContactItem(BaseModel):
    id: str
    type: str  # email or phone
    value: str
    normalized_value: str
    country: Optional[str] = None
    confidence: float
    source_type: str
    context: Optional[str] = None
    url: str
    created_at: datetime


class ContactListResponse(BaseModel):
    total: int
    items: List[ContactItem]


class SystemStatsResponse(BaseModel):
    total_crawls: int
    active_crawls: int
    completed_crawls: int
    failed_crawls: int
    pages_crawled: int
    pages_failed: int
    emails_found: int
    phones_found: int
    linkedin_found: int = 0

