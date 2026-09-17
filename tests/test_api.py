import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.database import init_db


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_metrics_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/metrics")
        assert response.status_code == 200
        assert "crawler_pages_crawled_total" in response.text


@pytest.mark.asyncio
async def test_dashboard_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/")
        assert response.status_code == 200
        assert "Contact Discovery Bot" in response.text


@pytest.mark.asyncio
async def test_stats_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_crawls" in data
        assert "active_crawls" in data


@pytest.mark.asyncio
async def test_crawl_api_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Create crawl
        payload = {
            "start_url": "https://example.com",
            "max_pages": 10,
            "max_depth": 2,
            "requests_per_second": 2.0,
            "concurrency": 2,
        }
        res = await ac.post("/api/crawls", json=payload)
        assert res.status_code == 202
        data = res.json()
        crawl_id = data["crawl_id"]
        assert data["status"] in ("queued", "running")

        # 2. Get status
        status_res = await ac.get(f"/api/crawls/{crawl_id}")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["crawl_id"] == crawl_id

        # 3. List crawls
        list_res = await ac.get("/api/crawls")
        assert list_res.status_code == 200
        all_crawls = list_res.json()
        assert any(c["crawl_id"] == crawl_id for c in all_crawls)

        # 4. Stop crawl
        stop_res = await ac.post(f"/api/crawls/{crawl_id}/stop")
        assert stop_res.status_code in (200, 400)

        # 5. Contacts list endpoint
        contacts_res = await ac.get(f"/api/crawls/{crawl_id}/contacts")
        assert contacts_res.status_code == 200
        assert "items" in contacts_res.json()
