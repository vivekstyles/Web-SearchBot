from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.db.repository import CrawlRepository
from app.schemas.contact import ContactListResponse, ContactItem

router = APIRouter(prefix="/api/contacts", tags=["Contacts"])


@router.get("", response_model=ContactListResponse)
async def list_all_contacts(
    type: Optional[str] = Query(None, description="Filter by type: 'email' or 'phone'"),
    job_id: Optional[str] = Query(None, description="Filter by crawl job ID"),
    search: Optional[str] = Query(None, description="Search term for value or URL"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Lists contacts discovered across all crawls with pagination and filtering."""
    repo = CrawlRepository(db)
    contacts, total = await repo.list_contacts(
        job_id=job_id,
        contact_type=type,
        search=search,
        limit=limit,
        offset=offset,
    )
    items = [ContactItem(**c) for c in contacts]
    return ContactListResponse(total=total, items=items)
