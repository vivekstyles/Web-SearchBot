import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from redis.asyncio import Redis

from app.config import get_settings
from app.db.database import init_db
from app.api.routes import (
    crawls_router,
    contacts_router,
    stats_router,
    metrics_router,
)
from app.services.crawl_service import crawl_service

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("contact_crawler")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    await init_db()

    # Optional Redis connection
    if settings.REDIS_URL:
        try:
            r = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.ping()
            crawl_service.redis_client = r
            logger.info("Connected to Redis at %s", settings.REDIS_URL)
        except Exception as e:
            logger.info("Redis not reachable (%s); running with in-memory queue fallback", e)
            crawl_service.redis_client = None

    yield

    # Shutdown
    if crawl_service.redis_client:
        await crawl_service.redis_client.aclose()
    logger.info("Crawler application shut down.")


app = FastAPI(
    title="Contact Discovery Bot API",
    description="Production-ready asynchronous web crawler and contact information discovery engine.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(crawls_router)
app.include_router(contacts_router)
app.include_router(stats_router)
app.include_router(metrics_router)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "contact-discovery-bot",
        "version": "1.0.0",
    }


# Static and Admin Dashboard frontend
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def serve_dashboard():
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "Admin dashboard frontend not found"}
