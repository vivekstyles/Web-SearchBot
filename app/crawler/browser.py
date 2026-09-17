import asyncio
import hashlib
import logging
import time
from typing import Optional

from app.crawler.fetcher import FetchResult
from app.config import get_settings

logger = logging.getLogger(__name__)


class PlaywrightRenderer:
    """
    Optional Playwright-based client-side browser renderer (Mode 2).
    Used selectively for JS-heavy Single Page Applications (SPAs) or when
    raw HTTP responses contain minimal content on contact pages.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._browser = None
        self._playwright = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import playwright  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    async def render_page(self, url: str) -> Optional[FetchResult]:
        if not self.is_available():
            logger.info("Playwright is not installed; skipping browser rendering.")
            return None

        from playwright.async_api import async_playwright

        start_time = time.perf_counter()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
                )
                context = await browser.new_context(
                    user_agent=get_settings().CRAWLER_USER_AGENT,
                    ignore_https_errors=True,
                )
                # Optimize: block heavy resources (images, media, fonts)
                await context.route(
                    "**/*",
                    lambda route: (
                        route.abort()
                        if route.request.resource_type in ["image", "media", "font"]
                        else route.continue_()
                    ),
                )
                page = await context.new_page()

                response = await page.goto(
                    url,
                    timeout=int(self.timeout * 1000),
                    wait_until="domcontentloaded",
                )
                # Wait a brief moment for dynamic hydration
                await asyncio.sleep(1.0)

                content = await page.content()
                status = response.status if response else 200
                headers = await response.all_headers() if response else {}
                content_type = headers.get("content-type", "text/html")
                await browser.close()

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                return FetchResult(
                    url=url,
                    status_code=status,
                    headers=headers,
                    content=content,
                    content_type=content_type,
                    response_time_ms=elapsed_ms,
                    content_hash=content_hash,
                )
        except Exception as e:
            logger.warning("Playwright rendering failed for %s: %s", url, e)
            return None
