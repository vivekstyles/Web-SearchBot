import asyncio
import time
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class DomainRateLimiter:
    """
    Per-domain rate limiter and concurrency coordinator.
    Ensures politeness by spacing requests per domain according to
    configured requests_per_second and robots.txt Crawl-delay.
    """

    def __init__(self, default_rps: float = 2.0, max_concurrency_per_domain: int = 2):
        self.default_rps = default_rps
        self.max_concurrency_per_domain = max_concurrency_per_domain
        self._last_request_time: Dict[str, float] = {}
        self._crawl_delays: Dict[str, float] = {}
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self.rate_limit_events: int = 0

    async def _get_domain_lock_and_sem(
        self, domain: str
    ) -> Tuple[asyncio.Lock, asyncio.Semaphore]:
        async with self._global_lock:
            if domain not in self._locks:
                self._locks[domain] = asyncio.Lock()
            if domain not in self._semaphores:
                self._semaphores[domain] = asyncio.Semaphore(
                    self.max_concurrency_per_domain
                )
            return self._locks[domain], self._semaphores[domain]

    def set_crawl_delay(self, domain: str, delay: float) -> None:
        """Sets the robots.txt Crawl-delay for a specific domain."""
        if delay > 0:
            self._crawl_delays[domain] = delay

    async def acquire(self, domain: str, requests_per_second: float = 0.0) -> None:
        """
        Blocks until the caller is permitted to send a request to the domain.
        """
        lock, sem = await self._get_domain_lock_and_sem(domain)
        await sem.acquire()

        async with lock:
            now = time.monotonic()
            last = self._last_request_time.get(domain, 0.0)

            # Determine minimum interval
            rps = requests_per_second or self.default_rps
            interval = 1.0 / rps if rps > 0 else 0.5

            crawl_delay = self._crawl_delays.get(domain, 0.0)
            target_delay = max(interval, crawl_delay)

            elapsed = now - last
            if elapsed < target_delay:
                wait_time = target_delay - elapsed
                self.rate_limit_events += 1
                logger.debug(
                    "Rate limit for %s: sleeping %.2fs (target interval: %.2fs)",
                    domain,
                    wait_time,
                    target_delay,
                )
                await asyncio.sleep(wait_time)

            self._last_request_time[domain] = time.monotonic()

    async def release(self, domain: str) -> None:
        """Releases the domain concurrency semaphore."""
        async with self._global_lock:
            sem = self._semaphores.get(domain)
        if sem:
            sem.release()
