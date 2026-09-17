import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Set

logger = logging.getLogger(__name__)


class AbstractCrawlQueue(ABC):
    @abstractmethod
    async def push(self, url: str, depth: int, priority: int = 50) -> bool:
        """Add URL to queue if not already queued or visited."""
        pass

    @abstractmethod
    async def pop(self) -> Optional[Tuple[str, int]]:
        """Retrieve the highest priority (url, depth) from queue."""
        pass

    @abstractmethod
    async def is_visited(self, url: str) -> bool:
        """Check if URL was already fetched."""
        pass

    @abstractmethod
    async def mark_visited(self, url: str) -> None:
        """Mark URL as visited."""
        pass

    @abstractmethod
    async def size(self) -> int:
        """Number of items remaining in queue."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear queue and visited sets."""
        pass


class MemoryCrawlQueue(AbstractCrawlQueue):
    """In-memory priority queue using asyncio.PriorityQueue and sets."""

    def __init__(self):
        self._queue = asyncio.PriorityQueue()
        self._visited: Set[str] = set()
        self._enqueued: Set[str] = set()
        self._lock = asyncio.Lock()
        self._counter = 0  # Tie-breaker for PriorityQueue

    async def push(self, url: str, depth: int, priority: int = 50) -> bool:
        async with self._lock:
            if url in self._visited or url in self._enqueued:
                return False
            self._enqueued.add(url)
            self._counter += 1
            # Lower number in PriorityQueue pops first, so negate priority
            await self._queue.put((-priority, self._counter, url, depth))
            return True

    async def pop(self) -> Optional[Tuple[str, int]]:
        async with self._lock:
            if self._queue.empty():
                return None
            try:
                neg_prio, cnt, url, depth = self._queue.get_nowait()
                self._enqueued.discard(url)
                return url, depth
            except asyncio.QueueEmpty:
                return None

    async def is_visited(self, url: str) -> bool:
        async with self._lock:
            return url in self._visited

    async def mark_visited(self, url: str) -> None:
        async with self._lock:
            self._visited.add(url)
            self._enqueued.discard(url)

    async def size(self) -> int:
        return self._queue.qsize()

    async def clear(self) -> None:
        async with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self._visited.clear()
            self._enqueued.clear()


class RedisCrawlQueue(AbstractCrawlQueue):
    """Redis-backed priority queue using ZSET and SET."""

    def __init__(self, redis_client, job_id: str):
        self.redis = redis_client
        self.job_id = job_id
        self.queue_key = f"crawl:{job_id}:queue"
        self.visited_key = f"crawl:{job_id}:visited"
        self.enqueued_key = f"crawl:{job_id}:enqueued"

    async def push(self, url: str, depth: int, priority: int = 50) -> bool:
        try:
            # Check if already visited or enqueued
            is_vis = await self.redis.sismember(self.visited_key, url)
            if is_vis:
                return False

            is_enq = await self.redis.sismember(self.enqueued_key, url)
            if is_enq:
                return False

            payload = json.dumps({"url": url, "depth": depth})
            # Add to set and sorted set atomically
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sadd(self.enqueued_key, url)
                pipe.zadd(self.queue_key, {payload: priority})
                await pipe.execute()
            return True
        except Exception as e:
            logger.warning("Redis push error: %s", e)
            return False

    async def pop(self) -> Optional[Tuple[str, int]]:
        try:
            # Pop highest priority (highest score) item
            items = await self.redis.zpopmax(self.queue_key, count=1)
            if not items:
                return None

            payload_raw, score = items[0]
            data = json.loads(payload_raw)
            url = data["url"]
            depth = data["depth"]
            await self.redis.srem(self.enqueued_key, url)
            return url, depth
        except Exception as e:
            logger.warning("Redis pop error: %s", e)
            return None

    async def is_visited(self, url: str) -> bool:
        try:
            return bool(await self.redis.sismember(self.visited_key, url))
        except Exception as e:
            logger.warning("Redis is_visited error: %s", e)
            return False

    async def mark_visited(self, url: str) -> None:
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sadd(self.visited_key, url)
                pipe.srem(self.enqueued_key, url)
                await pipe.execute()
        except Exception as e:
            logger.warning("Redis mark_visited error: %s", e)

    async def size(self) -> int:
        try:
            return await self.redis.zcard(self.queue_key)
        except Exception as e:
            logger.warning("Redis size error: %s", e)
            return 0

    async def clear(self) -> None:
        try:
            await self.redis.delete(self.queue_key, self.visited_key, self.enqueued_key)
        except Exception as e:
            logger.warning("Redis clear error: %s", e)
