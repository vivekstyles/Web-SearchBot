from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class CrawlRequest(BaseModel):
    start_url: str = Field(..., description="The seed URL to begin crawling from")
    max_pages: Optional[int] = Field(500, ge=1, le=10000, description="Maximum pages to crawl")
    max_depth: Optional[int] = Field(5, ge=0, le=20, description="Maximum crawl depth")
    requests_per_second: Optional[float] = Field(2.0, ge=0.1, le=20.0, description="Rate limit per domain")
    concurrency: Optional[int] = Field(5, ge=1, le=20, description="Concurrent fetch workers")
    respect_robots_txt: Optional[bool] = Field(True, description="Strictly respect robots.txt rules")
    follow_external_links: Optional[bool] = Field(False, description="Whether to follow out-of-domain links")
    include_subdomains: Optional[bool] = Field(True, description="Whether to allow subdomains of the start domain")
    allowed_domains: Optional[List[str]] = Field(None, description="Explicit list of permitted domains")
    user_agent: Optional[str] = Field(None, description="Custom User-Agent header")


class CrawlStartResponse(BaseModel):
    crawl_id: str
    status: str
    start_url: str


class CrawlStatusResponse(BaseModel):
    crawl_id: str
    status: str
    start_url: str
    max_pages: int
    max_depth: int
    pages_crawled: int
    pages_failed: int
    emails_found: int
    phones_found: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class CrawlPageItem(BaseModel):
    id: str
    url: str
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    depth: int
    title: Optional[str] = None
    response_time_ms: Optional[float] = None
    crawled_at: datetime


class CrawlPageListResponse(BaseModel):
    total: int
    items: List[CrawlPageItem]
