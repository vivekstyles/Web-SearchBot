import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_service
from app.db.repository import CrawlRepository
from app.schemas.contact import ContactListResponse, ContactItem
from app.schemas.crawl import (
    CrawlRequest,
    CrawlStartResponse,
    CrawlStatusResponse,
    CrawlPageListResponse,
    CrawlPageItem,
)
from app.services.crawl_service import CrawlService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crawls", tags=["Crawls"])


@router.post("", response_model=CrawlStartResponse, status_code=202)
async def start_crawl(
    req: CrawlRequest,
    db: AsyncSession = Depends(get_db),
    service: CrawlService = Depends(get_service),
):
    """Initiates a new asynchronous website crawl."""
    try:
        job = await service.start_crawl(req, db)
        return CrawlStartResponse(
            crawl_id=job.id,
            status=job.status,
            start_url=job.start_url,
        )
    except Exception as e:
        logger.exception("Failed to start crawl: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[CrawlStatusResponse])
async def list_crawls(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Lists all crawl jobs."""
    repo = CrawlRepository(db)
    jobs, _ = await repo.list_jobs(limit=limit, offset=offset)
    return [
        CrawlStatusResponse(
            crawl_id=job.id,
            status=job.status,
            start_url=job.start_url,
            max_pages=job.max_pages,
            max_depth=job.max_depth,
            pages_crawled=job.pages_crawled,
            pages_failed=job.pages_failed,
            emails_found=job.emails_found,
            phones_found=job.phones_found,
            linkedin_found=getattr(job, "linkedin_found", 0),
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
        )
        for job in jobs
    ]


@router.get("/{crawl_id}", response_model=CrawlStatusResponse)
async def get_crawl(
    crawl_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieves live status and metrics for a specific crawl job."""
    repo = CrawlRepository(db)
    job = await repo.get_job(crawl_id)
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")

    return CrawlStatusResponse(
        crawl_id=job.id,
        status=job.status,
        start_url=job.start_url,
        max_pages=job.max_pages,
        max_depth=job.max_depth,
        pages_crawled=job.pages_crawled,
        pages_failed=job.pages_failed,
        emails_found=job.emails_found,
        phones_found=job.phones_found,
        linkedin_found=getattr(job, "linkedin_found", 0),
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
    )


@router.post("/{crawl_id}/stop")
async def stop_crawl(
    crawl_id: str,
    db: AsyncSession = Depends(get_db),
    service: CrawlService = Depends(get_service),
):
    """Stops an ongoing crawl."""
    stopped = await service.stop_crawl(crawl_id, db)
    if not stopped:
        raise HTTPException(status_code=400, detail="Crawl is not running or not found")
    return {"message": "Crawl stopped successfully", "crawl_id": crawl_id}


@router.get("/{crawl_id}/contacts", response_model=ContactListResponse)
async def get_crawl_contacts(
    crawl_id: str,
    type: Optional[str] = Query(None, description="Filter by 'email' or 'phone'"),
    search: Optional[str] = Query(None, description="Search term"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Returns contacts discovered during a specific crawl."""
    repo = CrawlRepository(db)
    contacts, total = await repo.list_contacts(
        job_id=crawl_id,
        contact_type=type,
        search=search,
        limit=limit,
        offset=offset,
    )
    items = [ContactItem(**c) for c in contacts]
    return ContactListResponse(total=total, items=items)


@router.get("/{crawl_id}/contacts/export")
async def export_crawl_contacts(
    crawl_id: str,
    format: str = Query("json", pattern="^(json|csv)$"),
    db: AsyncSession = Depends(get_db),
    service: CrawlService = Depends(get_service),
):
    """Exports contacts discovered in a crawl in JSON or CSV format."""
    content, media_type = await service.export_contacts(
        job_id=crawl_id, session=db, export_format=format
    )
    filename = f"contacts_{crawl_id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=content, media_type=media_type, headers=headers)


@router.get("/{crawl_id}/pages", response_model=CrawlPageListResponse)
async def get_crawl_pages(
    crawl_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Returns web pages crawled during a specific job."""
    repo = CrawlRepository(db)
    pages, total = await repo.list_pages_by_job(crawl_id, limit=limit, offset=offset)
    items = [
        CrawlPageItem(
            id=p.id,
            url=p.url,
            status_code=p.status_code,
            content_type=p.content_type,
            depth=p.depth,
            title=p.title,
            response_time_ms=p.response_time_ms,
            crawled_at=p.crawled_at,
        )
        for p in pages
    ]
    return CrawlPageListResponse(total=total, items=items)
