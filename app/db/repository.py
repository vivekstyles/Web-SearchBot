import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy import select, update, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Domain, CrawlJob, Page, Contact, ContactSource, utc_now

logger = logging.getLogger(__name__)


class CrawlRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # Domain methods
    async def get_or_create_domain(self, domain_name: str) -> Domain:
        stmt = select(Domain).where(Domain.domain == domain_name)
        res = await self.session.execute(stmt)
        domain = res.scalar_one_or_none()
        if not domain:
            domain = Domain(domain=domain_name)
            self.session.add(domain)
            await self.session.flush()
        return domain

    async def update_domain_robots(
        self, domain_name: str, robots_txt: Optional[str], crawl_delay: float = 0.0
    ) -> Domain:
        domain = await self.get_or_create_domain(domain_name)
        domain.robots_txt = robots_txt
        domain.robots_fetched_at = utc_now()
        domain.crawl_delay = crawl_delay
        domain.updated_at = utc_now()
        await self.session.flush()
        return domain

    # CrawlJob methods
    async def create_job(
        self,
        start_url: str,
        max_pages: int,
        max_depth: int,
        config: Optional[dict] = None,
    ) -> CrawlJob:
        job = CrawlJob(
            start_url=start_url,
            max_pages=max_pages,
            max_depth=max_depth,
            status="queued",
            config=config or {},
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job(self, job_id: str) -> Optional[CrawlJob]:
        stmt = select(CrawlJob).where(CrawlJob.id == job_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_jobs(self, limit: int = 50, offset: int = 0) -> Tuple[List[CrawlJob], int]:
        count_stmt = select(func.count(CrawlJob.id))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = select(CrawlJob).order_by(CrawlJob.created_at.desc()).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        jobs = list(res.scalars().all())
        return jobs, total

    async def update_job_status(
        self,
        job_id: str,
        status: str,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        values: Dict[str, Any] = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at

        stmt = update(CrawlJob).where(CrawlJob.id == job_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()

    async def increment_job_stats(
        self,
        job_id: str,
        pages_crawled: int = 0,
        pages_failed: int = 0,
        emails_found: int = 0,
        phones_found: int = 0,
    ) -> None:
        stmt = (
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(
                pages_crawled=CrawlJob.pages_crawled + pages_crawled,
                pages_failed=CrawlJob.pages_failed + pages_failed,
                emails_found=CrawlJob.emails_found + emails_found,
                phones_found=CrawlJob.phones_found + phones_found,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    # Page methods
    async def create_page(
        self,
        crawl_job_id: str,
        url: str,
        status_code: Optional[int],
        content_type: Optional[str],
        depth: int,
        title: Optional[str] = None,
        content_hash: Optional[str] = None,
        response_time_ms: Optional[float] = None,
    ) -> Page:
        page = Page(
            crawl_job_id=crawl_job_id,
            url=url,
            status_code=status_code,
            content_type=content_type,
            depth=depth,
            title=title,
            content_hash=content_hash,
            response_time_ms=response_time_ms,
        )
        self.session.add(page)
        await self.session.flush()
        return page

    async def list_pages_by_job(
        self, job_id: str, limit: int = 100, offset: int = 0
    ) -> Tuple[List[Page], int]:
        count_stmt = select(func.count(Page.id)).where(Page.crawl_job_id == job_id)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Page)
            .where(Page.crawl_job_id == job_id)
            .order_by(Page.crawled_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), total

    # Contact and ContactSource methods with deduplication
    async def save_contacts(
        self,
        crawl_job_id: str,
        page_id: str,
        extracted_contacts: List[Dict[str, Any]],
    ) -> Tuple[int, int]:
        """
        Saves contacts and sources, deduplicating contacts across the database.
        Returns: (new_emails_count, new_phones_count)
        """
        new_emails = 0
        new_phones = 0

        for item in extracted_contacts:
            c_type = item["type"]
            val = item["value"]
            norm_val = item["normalized_value"]
            country = item.get("country")
            confidence = float(item.get("confidence", 1.0))
            context = item.get("context")
            source_type = item.get("source_type", "body")

            # Check if contact already exists
            stmt = select(Contact).where(
                Contact.type == c_type,
                Contact.normalized_value == norm_val,
            )
            res = await self.session.execute(stmt)
            contact = res.scalar_one_or_none()

            if not contact:
                contact = Contact(
                    type=c_type,
                    value=val,
                    normalized_value=norm_val,
                    country=country,
                    confidence=confidence,
                )
                self.session.add(contact)
                await self.session.flush()

            # Check if this contact was already linked to this crawl job
            job_linked_stmt = select(ContactSource.id).where(
                ContactSource.contact_id == contact.id,
                ContactSource.crawl_job_id == crawl_job_id,
            )
            job_linked = (await self.session.execute(job_linked_stmt)).first() is not None

            # Link with page via ContactSource if not already linked
            source_stmt = select(ContactSource).where(
                ContactSource.contact_id == contact.id,
                ContactSource.page_id == page_id,
            )
            src_res = await self.session.execute(source_stmt)
            source = src_res.scalar_one_or_none()

            if not source:
                source = ContactSource(
                    contact_id=contact.id,
                    page_id=page_id,
                    crawl_job_id=crawl_job_id,
                    context=context[:500] if context else None,
                    source_type=source_type,
                )
                self.session.add(source)
                await self.session.flush()

                if not job_linked:
                    if c_type == "email":
                        new_emails += 1
                    elif c_type == "phone":
                        new_phones += 1
            else:
                # Update confidence if higher
                if confidence > contact.confidence:
                    contact.confidence = confidence
                    if country and not contact.country:
                        contact.country = country
                    await self.session.flush()

        return new_emails, new_phones

    async def list_contacts(
        self,
        job_id: Optional[str] = None,
        contact_type: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List contacts matching filters with their sources.
        """
        # Build query joining Contact, ContactSource, Page
        stmt = (
            select(Contact, ContactSource, Page)
            .join(ContactSource, Contact.id == ContactSource.contact_id)
            .join(Page, ContactSource.page_id == Page.id)
        )

        conditions = []
        if job_id:
            conditions.append(ContactSource.crawl_job_id == job_id)
        if contact_type:
            conditions.append(Contact.type == contact_type)
        if search:
            search_pattern = f"%{search}%"
            conditions.append(
                or_(
                    Contact.value.ilike(search_pattern),
                    Contact.normalized_value.ilike(search_pattern),
                    Page.url.ilike(search_pattern),
                )
            )

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Count total
        count_stmt = (
            select(func.count(ContactSource.id))
            .select_from(Contact)
            .join(ContactSource, Contact.id == ContactSource.contact_id)
            .join(Page, ContactSource.page_id == Page.id)
        )
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Contact.created_at.desc()).limit(limit).offset(offset)
        res = await self.session.execute(stmt)

        results = []
        for contact, source, page in res.all():
            results.append({
                "id": contact.id,
                "type": contact.type,
                "value": contact.value,
                "normalized_value": contact.normalized_value,
                "country": contact.country,
                "confidence": contact.confidence,
                "source_type": source.source_type,
                "context": source.context,
                "url": page.url,
                "created_at": source.created_at,
            })

        return results, total
