import asyncio
import threading
from http.server import HTTPServer
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.crawler.engine import CrawlEngine
from app.crawler.queue import MemoryCrawlQueue
from app.db.models import Base
from app.db.repository import CrawlRepository
from app.services.crawl_service import CrawlService
from scripts.mock_website import MockWebsiteHandler


@pytest.fixture(scope="module")
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), MockWebsiteHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest_asyncio.fixture
async def test_db():
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
async def test_end_to_end_crawl(mock_server, test_db):
    start_url = f"{mock_server}/"

    async with test_db() as session:
        repo = CrawlRepository(session)
        job = await repo.create_job(
            start_url=start_url,
            max_pages=50,
            max_depth=3,
        )
        job_id = job.id
        await session.commit()

    queue = MemoryCrawlQueue()

    engine = CrawlEngine(
        job_id=job_id,
        start_url=start_url,
        queue=queue,
        session_factory=test_db,
        max_pages=50,
        max_depth=3,
        requests_per_second=20.0,  # Fast for test
        concurrency=3,
        respect_robots_txt=True,
        allow_private_ips=True,  # Crucial for local mock server
    )

    # Run crawl
    await engine.run()

    # Verify database contents
    async with test_db() as session:
        repo = CrawlRepository(session)
        job = await repo.get_job(job_id)
        assert job is not None
        assert job.status == "completed"
        assert job.pages_crawled >= 4
        assert job.emails_found >= 4
        assert job.phones_found >= 4

        # Verify pages crawled
        pages, total_pages = await repo.list_pages_by_job(job_id, limit=100)
        crawled_urls = [p.url for p in pages]

        # robots.txt verification: /disallowed must NOT be crawled!
        disallowed_url = f"{mock_server}/disallowed"
        assert disallowed_url not in crawled_urls

        # Verify contacts
        contacts, total_contacts = await repo.list_contacts(job_id=job_id, limit=100)
        emails = [c["normalized_value"] for c in contacts if c["type"] == "email"]
        phones = [c["normalized_value"] for c in contacts if c["type"] == "phone"]

        # Check standard emails
        assert "info@example.org" in emails
        assert "press@example.org" in emails
        assert "support@example.org" in emails
        assert "inquiries@example.org" in emails
        assert "alice.smith@example.org" in emails
        assert "bob.jones+dev@example.org" in emails

        # Check de-obfuscated email
        assert "security@example.com" in emails

        # Check disallowed page leak email is NOT found
        assert "forbidden_leak@example.org" not in emails

        # Check US & International phone numbers normalized to E.164
        assert "+18005550199" in phones
        assert "+15553456789" in phones
        assert "+15552345678" in phones
        assert "+15559876543" in phones
        assert "+442079460958" in phones
        assert "+919876543210" in phones

        # Deduplication check: each normalized contact appears only once in contacts table
        from sqlalchemy import select
        from app.db.models import Contact
        unique_contacts = (await session.execute(select(Contact))).scalars().all()
        assert len(unique_contacts) == len(set(c.normalized_value for c in unique_contacts))
        assert len(unique_contacts) == 13

        # Check context
        support_contact = next(c for c in contacts if c["normalized_value"] == "support@example.org")
        assert support_contact["context"] is not None
        assert "support" in support_contact["context"].lower()

        # Test CSV & JSON Export
        service = CrawlService()
        csv_data, csv_type = await service.export_contacts(job_id, session, export_format="csv")
        assert "text/csv" in csv_type
        assert "support@example.org" in csv_data
        assert "+15552345678" in csv_data

        json_data, json_type = await service.export_contacts(job_id, session, export_format="json")
        assert "application/json" in json_type
        assert "support@example.org" in json_data
