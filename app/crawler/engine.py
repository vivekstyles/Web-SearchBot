import asyncio
import logging
import time
from typing import List, Optional, Callable, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crawler.browser import PlaywrightRenderer
from app.crawler.fetcher import AsyncHttpFetcher, FetchResult
from app.crawler.metrics import (
    PAGES_CRAWLED_TOTAL,
    PAGES_FAILED_TOTAL,
    EMAILS_FOUND_TOTAL,
    PHONES_FOUND_TOTAL,
    BYTES_DOWNLOADED_TOTAL,
    RESPONSE_DURATION_SECONDS,
    ROBOTS_DENIED_TOTAL,
    ACTIVE_CRAWLS_GAUGE,
)
from app.crawler.queue import AbstractCrawlQueue
from app.crawler.robots import RobotsManager
from app.crawler.scheduler import DomainRateLimiter
from app.crawler.sitemap import SitemapParser
from app.crawler.url import (
    normalize_url,
    get_domain,
    is_same_domain,
    is_likely_contact_url,
)
from app.db.models import utc_now
from app.db.repository import CrawlRepository
from app.extractors.email import EmailExtractor
from app.extractors.html import ParsedHtmlDocument
from app.extractors.phone import PhoneExtractor

logger = logging.getLogger(__name__)


class CrawlEngine:
    """
    Asynchronous Crawl Engine coordinating:
    - Queue management
    - robots.txt & Crawl-delay adherence
    - Sitemap discovery
    - Fetching (HTTP + optional Playwright)
    - Link extraction & prioritization
    - Contact extraction (Email, Phone)
    - Normalization, validation, deduplication
    - Database persistence & Prometheus metrics
    """

    def __init__(
        self,
        job_id: str,
        start_url: str,
        queue: AbstractCrawlQueue,
        session_factory: Callable[[], AsyncSession],
        allowed_domains: Optional[List[str]] = None,
        max_pages: int = 500,
        max_depth: int = 5,
        requests_per_second: float = 2.0,
        concurrency: int = 5,
        respect_robots_txt: bool = True,
        follow_external_links: bool = False,
        include_subdomains: bool = True,
        user_agent: Optional[str] = None,
        allow_private_ips: Optional[bool] = None,
        enable_browser_rendering: Optional[bool] = None,
    ):
        settings = get_settings()
        self.job_id = job_id
        self.start_url = normalize_url(start_url) or start_url
        self.queue = queue
        self.session_factory = session_factory

        start_domain = get_domain(self.start_url)
        self.allowed_domains = allowed_domains or [start_domain]
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.requests_per_second = requests_per_second
        self.concurrency = concurrency
        self.respect_robots_txt = respect_robots_txt
        self.follow_external_links = follow_external_links
        self.include_subdomains = include_subdomains
        self.user_agent = user_agent or settings.CRAWLER_USER_AGENT
        self.allow_private_ips = (
            allow_private_ips
            if allow_private_ips is not None
            else settings.ALLOW_PRIVATE_IPS
        )
        self.enable_browser = (
            enable_browser_rendering
            if enable_browser_rendering is not None
            else settings.ENABLE_BROWSER_RENDERING
        )

        self.fetcher = AsyncHttpFetcher(
            user_agent=self.user_agent,
            timeout=settings.DEFAULT_TIMEOUT,
            max_redirects=settings.MAX_REDIRECTS,
            max_response_size_bytes=settings.max_response_size_bytes,
            allow_private_ips=self.allow_private_ips,
        )
        self.browser = PlaywrightRenderer() if self.enable_browser else None
        self.rate_limiter = DomainRateLimiter(
            default_rps=self.requests_per_second,
            max_concurrency_per_domain=self.concurrency,
        )
        self.robots_manager = RobotsManager()

        self._is_running = False
        self._is_stopped = False
        self._pages_crawled = 0
        self._pages_failed = 0
        self._active_workers = 0
        self._workers_lock = asyncio.Lock()

    def stop(self) -> None:
        """Signal engine to gracefully halt crawling."""
        self._is_stopped = True

    async def _fetch_text_wrapper(self, url: str) -> Tuple[int, Optional[str]]:
        """Helper to fetch raw text for robots.txt or sitemaps."""
        res = await self.fetcher.fetch(url, max_retries=1)
        return res.status_code, res.content if res.is_success else None

    async def run(self) -> None:
        ACTIVE_CRAWLS_GAUGE.inc()
        self._is_running = True
        start_timestamp = utc_now()

        async with self.session_factory() as session:
            repo = CrawlRepository(session)
            await repo.update_job_status(
                self.job_id, status="running", started_at=start_timestamp
            )
            await session.commit()

        start_domain = get_domain(self.start_url)
        logger.info(
            "Starting crawl job %s for %s (domain: %s)",
            self.job_id,
            self.start_url,
            start_domain,
        )

        try:
            # 1. Inspect robots.txt
            domain_robots = None
            if self.respect_robots_txt:
                domain_robots = await self.robots_manager.get_robots(
                    self.start_url, self._fetch_text_wrapper, self.user_agent
                )
                if domain_robots.crawl_delay > 0:
                    self.rate_limiter.set_crawl_delay(
                        start_domain, domain_robots.crawl_delay
                    )

                # Persist robots.txt in database
                async with self.session_factory() as session:
                    repo = CrawlRepository(session)
                    await repo.update_domain_robots(
                        start_domain,
                        domain_robots.raw_content,
                        domain_robots.crawl_delay,
                    )
                    await session.commit()

                # Check if start_url is explicitly disallowed
                if not domain_robots.is_allowed(self.user_agent, self.start_url):
                    reason = f"Start URL {self.start_url} is disallowed by robots.txt"
                    logger.warning(reason)
                    ROBOTS_DENIED_TOTAL.labels(domain=start_domain).inc()
                    async with self.session_factory() as session:
                        repo = CrawlRepository(session)
                        await repo.update_job_status(
                            self.job_id,
                            status="failed",
                            error_message=reason,
                            completed_at=utc_now(),
                        )
                        await session.commit()
                    return

            # 2. Sitemap Discovery
            sitemap_candidates = []
            if domain_robots and domain_robots.sitemaps:
                sitemap_candidates.extend(domain_robots.sitemaps)
            from urllib.parse import urlparse
            p_start = urlparse(self.start_url)
            sitemap_candidates.append(f"{p_start.scheme}://{p_start.netloc}/sitemap.xml")

            discovered_sitemap_urls = await SitemapParser.discover_urls_from_sitemaps(
                sitemap_candidates,
                self._fetch_text_wrapper,
                self.allowed_domains,
                max_urls=min(self.max_pages, 200),
            )
            for s_url in discovered_sitemap_urls:
                if s_url != self.start_url:
                    await self.queue.push(s_url, depth=1, priority=50)

            # 3. Enqueue start URL with highest priority
            await self.queue.push(self.start_url, depth=0, priority=100)

            # 4. Spawn concurrent workers
            workers = [
                asyncio.create_task(self._worker_loop())
                for _ in range(self.concurrency)
            ]
            await asyncio.gather(*workers)

            final_status = "stopped" if self._is_stopped else "completed"
            logger.info("Crawl job %s finished with status: %s", self.job_id, final_status)

        except Exception as e:
            logger.exception("Crawl job %s encountered fatal error: %s", self.job_id, e)
            final_status = "failed"
            async with self.session_factory() as session:
                repo = CrawlRepository(session)
                await repo.update_job_status(
                    self.job_id,
                    status="failed",
                    error_message=str(e),
                    completed_at=utc_now(),
                )
                await session.commit()
            return
        finally:
            self._is_running = False
            ACTIVE_CRAWLS_GAUGE.dec()
            await self.fetcher.close()

            async with self.session_factory() as session:
                repo = CrawlRepository(session)
                await repo.update_job_status(
                    self.job_id, status=final_status, completed_at=utc_now()
                )
                await session.commit()

    async def _worker_loop(self) -> None:
        """Worker loop processing URLs from priority queue."""
        idle_cycles = 0

        while not self._is_stopped and self._pages_crawled < self.max_pages:
            item = await self.queue.pop()
            if not item:
                async with self._workers_lock:
                    if self._active_workers == 0:
                        # Queue is empty and no workers are fetching
                        break
                idle_cycles += 1
                if idle_cycles > 20:
                    break
                await asyncio.sleep(0.2)
                continue

            idle_cycles = 0
            url, depth = item

            # Check if URL was already visited
            if await self.queue.is_visited(url):
                continue
            await self.queue.mark_visited(url)

            domain = get_domain(url)

            # Check robots.txt
            if self.respect_robots_txt:
                robots = await self.robots_manager.get_robots(
                    url, self._fetch_text_wrapper, self.user_agent
                )
                if not robots.is_allowed(self.user_agent, url):
                    logger.info("robots.txt disallowed URL: %s", url)
                    ROBOTS_DENIED_TOTAL.labels(domain=domain).inc()
                    continue

            # Respect per-domain rate limit
            await self.rate_limiter.acquire(
                domain, requests_per_second=self.requests_per_second
            )

            async with self._workers_lock:
                self._active_workers += 1

            try:
                # Fetch page
                t0 = time.perf_counter()
                fetch_res = await self.fetcher.fetch(url)
                duration = time.perf_counter() - t0
                RESPONSE_DURATION_SECONDS.labels(domain=domain).observe(duration)

                if fetch_res.error or not fetch_res.is_success:
                    self._pages_failed += 1
                    PAGES_FAILED_TOTAL.labels(
                        domain=domain, reason=fetch_res.error or f"HTTP_{fetch_res.status_code}"
                    ).inc()

                    async with self.session_factory() as session:
                        repo = CrawlRepository(session)
                        await repo.create_page(
                            crawl_job_id=self.job_id,
                            url=url,
                            status_code=fetch_res.status_code or None,
                            content_type=fetch_res.content_type,
                            depth=depth,
                            response_time_ms=fetch_res.response_time_ms,
                        )
                        await repo.increment_job_stats(self.job_id, pages_failed=1)
                        await session.commit()
                    continue

                # Successful fetch
                self._pages_crawled += 1
                PAGES_CRAWLED_TOTAL.labels(
                    domain=domain, status=str(fetch_res.status_code)
                ).inc()
                BYTES_DOWNLOADED_TOTAL.labels(domain=domain).inc(
                    len(fetch_res.content.encode("utf-8"))
                )

                # Optional Playwright fallback if content is minimal
                if (
                    self.enable_browser
                    and self.browser
                    and len(fetch_res.content.strip()) < 500
                    and "id=\"root\"" in fetch_res.content
                ):
                    browser_res = await self.browser.render_page(url)
                    if browser_res and len(browser_res.content) > len(fetch_res.content):
                        fetch_res = browser_res

                # Parse HTML
                parsed_doc = ParsedHtmlDocument(fetch_res.content, url)

                # Extract links if within depth and budget
                if depth < self.max_depth and (self._pages_crawled + await self.queue.size()) < self.max_pages:
                    candidate_links = parsed_doc.get_links(
                        allowed_domains=self.allowed_domains,
                        include_subdomains=self.include_subdomains,
                        follow_external_links=self.follow_external_links,
                    )
                    for link_url, priority in candidate_links:
                        await self.queue.push(link_url, depth=depth + 1, priority=priority)

                # Extract Contacts
                text_nodes = parsed_doc.get_text_nodes_with_context()
                attr_contacts = parsed_doc.get_attribute_contacts()
                is_contact_pg, _ = is_likely_contact_url(url)

                emails = EmailExtractor.extract_from_nodes(
                    text_nodes, attr_contacts, is_contact_page=is_contact_pg
                )
                phones = PhoneExtractor.extract_from_nodes(
                    text_nodes, attr_contacts, domain=domain, is_contact_page=is_contact_pg
                )
                all_contacts = emails + phones

                # Persist Page and Contacts
                async with self.session_factory() as session:
                    repo = CrawlRepository(session)
                    page = await repo.create_page(
                        crawl_job_id=self.job_id,
                        url=url,
                        status_code=fetch_res.status_code,
                        content_type=fetch_res.content_type,
                        depth=depth,
                        title=parsed_doc.title,
                        content_hash=fetch_res.content_hash,
                        response_time_ms=fetch_res.response_time_ms,
                    )

                    new_emails, new_phones = await repo.save_contacts(
                        self.job_id, page.id, all_contacts
                    )
                    await repo.increment_job_stats(
                        self.job_id,
                        pages_crawled=1,
                        emails_found=new_emails,
                        phones_found=new_phones,
                    )
                    await session.commit()

                if new_emails > 0:
                    EMAILS_FOUND_TOTAL.labels(domain=domain).inc(new_emails)
                if new_phones > 0:
                    PHONES_FOUND_TOTAL.labels(domain=domain).inc(new_phones)

            except Exception as e:
                logger.warning("Error processing %s: %s", url, e)
            finally:
                await self.rate_limiter.release(domain)
                async with self._workers_lock:
                    self._active_workers -= 1
