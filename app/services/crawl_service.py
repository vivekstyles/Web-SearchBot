import asyncio
import csv
import io
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crawler.engine import CrawlEngine
from app.crawler.queue import AbstractCrawlQueue, MemoryCrawlQueue, RedisCrawlQueue
from app.db.database import AsyncSessionLocal
from app.db.models import CrawlJob, Contact, ContactSource, Page
from app.db.repository import CrawlRepository
from app.schemas.crawl import CrawlRequest

logger = logging.getLogger(__name__)


class CrawlService:
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self._active_engines: Dict[str, CrawlEngine] = {}
        self._lock = asyncio.Lock()

    def _create_queue(self, job_id: str) -> AbstractCrawlQueue:
        if self.redis_client:
            try:
                return RedisCrawlQueue(self.redis_client, job_id)
            except Exception as e:
                logger.warning("Failed to initialize Redis queue: %s, falling back to memory queue", e)
        return MemoryCrawlQueue()

    async def start_crawl(self, req: CrawlRequest, session: AsyncSession) -> CrawlJob:
        repo = CrawlRepository(session)
        job = await repo.create_job(
            start_url=req.start_url,
            max_pages=req.max_pages or 500,
            max_depth=req.max_depth or 5,
            config=req.model_dump(),
        )
        await session.commit()

        queue = self._create_queue(job.id)

        # Create engine
        engine = CrawlEngine(
            job_id=job.id,
            start_url=req.start_url,
            queue=queue,
            session_factory=AsyncSessionLocal,
            allowed_domains=req.allowed_domains,
            max_pages=req.max_pages or 500,
            max_depth=req.max_depth or 5,
            requests_per_second=req.requests_per_second or 2.0,
            concurrency=req.concurrency or 5,
            respect_robots_txt=req.respect_robots_txt if req.respect_robots_txt is not None else True,
            follow_external_links=req.follow_external_links or False,
            include_subdomains=req.include_subdomains if req.include_subdomains is not None else True,
            user_agent=req.user_agent,
        )

        async with self._lock:
            self._active_engines[job.id] = engine

        # Spawn engine execution in background
        async def _run_and_cleanup():
            try:
                await engine.run()
            finally:
                async with self._lock:
                    self._active_engines.pop(job.id, None)

        asyncio.create_task(_run_and_cleanup())
        return job

    async def stop_crawl(self, job_id: str, session: AsyncSession) -> bool:
        async with self._lock:
            engine = self._active_engines.get(job_id)
            if engine:
                engine.stop()

        repo = CrawlRepository(session)
        job = await repo.get_job(job_id)
        if job and job.status in ("queued", "running"):
            await repo.update_job_status(job_id, status="stopped")
            await session.commit()
            return True
        return False

    async def get_stats(self, session: AsyncSession) -> Dict[str, int]:
        total_crawls = (await session.execute(select(func.count(CrawlJob.id)))).scalar_one()
        active_crawls = (
            await session.execute(
                select(func.count(CrawlJob.id)).where(CrawlJob.status == "running")
            )
        ).scalar_one()
        completed_crawls = (
            await session.execute(
                select(func.count(CrawlJob.id)).where(CrawlJob.status == "completed")
            )
        ).scalar_one()
        failed_crawls = (
            await session.execute(
                select(func.count(CrawlJob.id)).where(CrawlJob.status == "failed")
            )
        ).scalar_one()

        pages_crawled = (
            await session.execute(select(func.coalesce(func.sum(CrawlJob.pages_crawled), 0)))
        ).scalar_one()
        pages_failed = (
            await session.execute(select(func.coalesce(func.sum(CrawlJob.pages_failed), 0)))
        ).scalar_one()
        emails_found = (
            await session.execute(
                select(func.count(Contact.id)).where(Contact.type == "email")
            )
        ).scalar_one()
        phones_found = (
            await session.execute(
                select(func.count(Contact.id)).where(Contact.type == "phone")
            )
        ).scalar_one()

        return {
            "total_crawls": total_crawls,
            "active_crawls": active_crawls,
            "completed_crawls": completed_crawls,
            "failed_crawls": failed_crawls,
            "pages_crawled": pages_crawled,
            "pages_failed": pages_failed,
            "emails_found": emails_found,
            "phones_found": phones_found,
        }

    async def export_contacts(
        self, job_id: str, session: AsyncSession, export_format: str = "json"
    ) -> Tuple[str, str]:
        """
        Exports contacts for a crawl job in CSV or JSON.
        Returns: (content_string, media_type)
        """
        repo = CrawlRepository(session)
        contacts, _ = await repo.list_contacts(job_id=job_id, limit=50000, offset=0)

        if export_format.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "type",
                "value",
                "normalized",
                "country",
                "confidence",
                "source_type",
                "source_url",
                "context",
            ])
            for c in contacts:
                writer.writerow([
                    c["type"],
                    c["value"],
                    c["normalized_value"],
                    c.get("country") or "",
                    f"{c['confidence']:.2f}",
                    c["source_type"],
                    c["url"],
                    c.get("context") or "",
                ])
            return output.getvalue(), "text/csv"

        # JSON export
        export_data = [
            {
                "type": c["type"],
                "value": c["value"],
                "normalized": c["normalized_value"],
                "country": c.get("country"),
                "confidence": round(c["confidence"], 2),
                "source_type": c["source_type"],
                "source_url": c["url"],
                "context": c.get("context"),
                "created_at": c["created_at"].isoformat() if hasattr(c["created_at"], "isoformat") else str(c["created_at"]),
            }
            for c in contacts
        ]
        return json.dumps(export_data, indent=2), "application/json"


# Singleton instance
crawl_service = CrawlService()
