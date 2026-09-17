from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_service
from app.schemas.contact import SystemStatsResponse
from app.services.crawl_service import CrawlService

router = APIRouter(prefix="/api/stats", tags=["Stats"])


@router.get("", response_model=SystemStatsResponse)
async def get_system_stats(
    db: AsyncSession = Depends(get_db),
    service: CrawlService = Depends(get_service),
):
    """Retrieves high-level statistics for the admin dashboard."""
    stats = await service.get_stats(db)
    return SystemStatsResponse(**stats)
