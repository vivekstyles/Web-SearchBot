from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.services.crawl_service import CrawlService, crawl_service


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


def get_service() -> CrawlService:
    return crawl_service
