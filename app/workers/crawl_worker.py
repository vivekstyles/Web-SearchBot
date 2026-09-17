import asyncio
import json
import logging
import signal
from typing import Optional
from redis.asyncio import Redis

from app.config import get_settings
from app.crawler.engine import CrawlEngine
from app.crawler.queue import RedisCrawlQueue
from app.db.database import AsyncSessionLocal, init_db
from app.schemas.crawl import CrawlRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("crawl_worker")

WORKER_QUEUE_KEY = "crawler:dispatch_queue"


class CrawlWorker:
    def __init__(self, redis_url: Optional[str] = None):
        self.settings = get_settings()
        self.redis_url = redis_url or self.settings.REDIS_URL
        self.redis: Optional[Redis] = None
        self._running = False

    async def start(self) -> None:
        await init_db()
        if not self.redis_url:
            logger.error("Redis URL not configured. Worker requires Redis.")
            return

        self.redis = Redis.from_url(self.redis_url, decode_responses=True)
        self._running = True
        logger.info("Worker started, listening on Redis key '%s'...", WORKER_QUEUE_KEY)

        while self._running:
            try:
                # Block for 2 seconds waiting for new dispatch job
                result = await self.redis.blpop([WORKER_QUEUE_KEY], timeout=2)
                if not result:
                    continue

                _, job_json = result
                job_data = json.loads(job_json)
                job_id = job_data["job_id"]
                req_dict = job_data["request"]
                req = CrawlRequest(**req_dict)

                logger.info("Worker picked up job %s (%s)", job_id, req.start_url)
                queue = RedisCrawlQueue(self.redis, job_id)

                engine = CrawlEngine(
                    job_id=job_id,
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

                await engine.run()
                logger.info("Worker finished job %s", job_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Worker loop error: %s", e)
                await asyncio.sleep(1.0)

        if self.redis:
            await self.redis.aclose()
        logger.info("Worker stopped.")

    def stop(self) -> None:
        self._running = False


async def main():
    worker = CrawlWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:
            pass  # Windows signal handling limitation
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
