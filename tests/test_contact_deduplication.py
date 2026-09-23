import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from app.db.models import Base, Contact, ContactSource
from app.db.repository import CrawlRepository


@pytest_asyncio.fixture
async def memory_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_contacts_strict_uniqueness(memory_db):
    """
    Verify that save_contacts strictly stores only unique contact values
    and creates at most one ContactSource per unique contact across multiple pages and jobs.
    """
    async with memory_db() as session:
        repo = CrawlRepository(session)
        job = await repo.create_job(start_url="https://example.com", max_pages=10, max_depth=2)
        page1 = await repo.create_page(crawl_job_id=job.id, url="https://example.com/page1", status_code=200, content_type="text/html", depth=1)
        page2 = await repo.create_page(crawl_job_id=job.id, url="https://example.com/page2", status_code=200, content_type="text/html", depth=1)
        await session.commit()

        # Batch 1 on Page 1: 1 email, 1 phone, 1 linkedin
        contacts_p1 = [
            {"type": "email", "value": "Admin@Example.COM", "normalized_value": "admin@example.com", "confidence": 0.8},
            {"type": "phone", "value": "(800) 555-0199", "normalized_value": "+18005550199", "country": "US", "confidence": 0.85},
            {"type": "linkedin", "value": "https://www.linkedin.com/company/Example-Corp", "normalized_value": "https://www.linkedin.com/company/example-corp", "confidence": 0.9},
        ]
        new_emails, new_phones, new_linkedin = await repo.save_contacts(job.id, page1.id, contacts_p1)
        await session.commit()

        assert new_emails == 1
        assert new_phones == 1
        assert new_linkedin == 1

        # Batch 2 on Page 2: Same contacts with higher confidence + 1 new email
        contacts_p2 = [
            {"type": "email", "value": "admin@example.com", "normalized_value": "admin@example.com", "confidence": 0.95},
            {"type": "phone", "value": "+1 800-555-0199", "normalized_value": "+18005550199", "country": "US", "confidence": 0.95},
            {"type": "linkedin", "value": "https://www.linkedin.com/company/example-corp", "normalized_value": "https://www.linkedin.com/company/example-corp", "confidence": 0.95},
            {"type": "email", "value": "sales@example.com", "normalized_value": "sales@example.com", "confidence": 0.9},
        ]
        new_emails, new_phones, new_linkedin = await repo.save_contacts(job.id, page2.id, contacts_p2)
        await session.commit()

        # Only the new email should be counted
        assert new_emails == 1
        assert new_phones == 0
        assert new_linkedin == 0

        # Check total records in contacts table
        contacts_db = (await session.execute(select(Contact))).scalars().all()
        assert len(contacts_db) == 4  # admin, phone, linkedin, sales

        # Check total records in contact_sources table
        sources_db = (await session.execute(select(ContactSource))).scalars().all()
        assert len(sources_db) == 4  # Exactly one source per unique contact!

        # Check updated confidence on existing contact
        admin_contact = next(c for c in contacts_db if c.normalized_value == "admin@example.com")
        assert admin_contact.confidence == 0.95

        # Check list_contacts returns exactly 4 items
        results, total = await repo.list_contacts(job_id=job.id)
        assert total == 4
        assert len(results) == 4
