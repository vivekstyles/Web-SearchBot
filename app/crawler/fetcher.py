import asyncio
import hashlib
import logging
import time
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.crawler.security import resolve_and_validate_host

logger = logging.getLogger(__name__)


class FetchResult:
    def __init__(
        self,
        url: str,
        status_code: int,
        headers: Dict[str, str],
        content: str,
        content_type: str,
        response_time_ms: float,
        content_hash: str,
        error: Optional[str] = None,
        redirected_urls: Optional[list] = None,
    ):
        self.url = url
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.content_type = content_type
        self.response_time_ms = response_time_ms
        self.content_hash = content_hash
        self.error = error
        self.redirected_urls = redirected_urls or []

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300 and not self.error


class AsyncHttpFetcher:
    """
    Robust, production-grade asynchronous HTTP fetcher with connection pooling,
    exponential backoff retries, SSRF defense, 429/Retry-After handling,
    content-type filtering, and response size guards.
    """

    ALLOWED_CONTENT_TYPES = (
        "text/html",
        "application/xhtml+xml",
        "text/plain",  # For robots.txt and sitemaps
        "text/xml",
        "application/xml",
    )

    def __init__(
        self,
        user_agent: Optional[str] = None,
        timeout: Optional[float] = None,
        max_redirects: Optional[int] = None,
        max_response_size_bytes: Optional[int] = None,
        allow_private_ips: Optional[bool] = None,
        max_connections: int = 50,
        max_keepalive: int = 20,
    ):
        settings = get_settings()
        self.user_agent = user_agent or settings.CRAWLER_USER_AGENT
        self.timeout = timeout or settings.DEFAULT_TIMEOUT
        self.max_redirects = max_redirects or settings.MAX_REDIRECTS
        self.max_response_size = (
            max_response_size_bytes or settings.max_response_size_bytes
        )
        self.allow_private_ips = (
            allow_private_ips
            if allow_private_ips is not None
            else settings.ALLOW_PRIVATE_IPS
        )

        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
            keepalive_expiry=30.0,
        )

        # Default headers
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.1",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Create httpx AsyncClient
        self.client = httpx.AsyncClient(
            limits=limits,
            headers=headers,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            follow_redirects=False,  # We manage redirects manually for SSRF inspection
            verify=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        max_retries: int = 2,
        backoff_factor: float = 0.5,
    ) -> FetchResult:
        current_url = url
        redirects_followed = 0
        redirect_history = []

        start_time = time.perf_counter()

        while redirects_followed <= self.max_redirects:
            # 1. SSRF pre-check on host
            parsed = urlparse(current_url)
            hostname = parsed.hostname
            if not hostname:
                return FetchResult(
                    url=current_url,
                    status_code=0,
                    headers={},
                    content="",
                    content_type="",
                    response_time_ms=0.0,
                    content_hash="",
                    error=f"Invalid URL hostname: {current_url}",
                )

            is_safe, error_msg = await resolve_and_validate_host(
                hostname, allow_private=self.allow_private_ips
            )
            if not is_safe:
                logger.warning("SSRF block for %s: %s", current_url, error_msg)
                return FetchResult(
                    url=current_url,
                    status_code=0,
                    headers={},
                    content="",
                    content_type="",
                    response_time_ms=0.0,
                    content_hash="",
                    error=f"Blocked by SSRF protection: {error_msg}",
                )

            # 2. Send request with retries
            response = None
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    # Stream response to check headers & size safely
                    req = self.client.build_request(method, current_url)
                    resp = await self.client.send(req, stream=True)

                    # Handle 429 Too Many Requests
                    if resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After")
                        wait_seconds = 2.0
                        if retry_after:
                            try:
                                wait_seconds = float(retry_after)
                            except ValueError:
                                try:
                                    dt = parsedate_to_datetime(retry_after)
                                    wait_seconds = max(
                                        0.0,
                                        (dt.timestamp() - time.time()),
                                    )
                                except Exception:
                                    pass
                        wait_seconds = min(wait_seconds, 15.0)  # cap max backoff
                        logger.info(
                            "HTTP 429 on %s, backing off for %.1fs",
                            current_url,
                            wait_seconds,
                        )
                        await resp.aclose()
                        await asyncio.sleep(wait_seconds)
                        continue

                    # Handle 502/503/504 retryable server errors
                    if resp.status_code in (502, 503, 504) and attempt < max_retries:
                        await resp.aclose()
                        wait_time = backoff_factor * (2**attempt)
                        logger.warning(
                            "HTTP %d on %s, retry %d in %.1fs",
                            resp.status_code,
                            current_url,
                            attempt + 1,
                            wait_time,
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    response = resp
                    break

                except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = backoff_factor * (2**attempt)
                        await asyncio.sleep(wait_time)
                    else:
                        break
                except Exception as e:
                    last_exception = e
                    break

            if response is None:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return FetchResult(
                    url=current_url,
                    status_code=0,
                    headers={},
                    content="",
                    content_type="",
                    response_time_ms=elapsed_ms,
                    content_hash="",
                    error=f"Connection failed: {str(last_exception)}",
                )

            # 3. Handle redirects (301, 302, 303, 307, 308)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                await response.aclose()
                if not location:
                    break

                # Resolve relative redirect
                from urllib.parse import urljoin
                next_url = urljoin(current_url, location)
                redirect_history.append(current_url)
                current_url = next_url
                redirects_followed += 1
                continue

            # 4. Validate Content-Type
            content_type_header = response.headers.get("Content-Type", "")
            content_type = content_type_header.split(";")[0].strip().lower()

            # Reject non-HTML/XML resources early
            if content_type and not any(
                content_type.startswith(act) for act in self.ALLOWED_CONTENT_TYPES
            ):
                await response.aclose()
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return FetchResult(
                    url=current_url,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content="",
                    content_type=content_type,
                    response_time_ms=elapsed_ms,
                    content_hash="",
                    error=f"Excluded content type: {content_type}",
                )

            # 5. Check Content-Length header if available
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > self.max_response_size:
                        await response.aclose()
                        elapsed_ms = (time.perf_counter() - start_time) * 1000
                        return FetchResult(
                            url=current_url,
                            status_code=response.status_code,
                            headers=dict(response.headers),
                            content="",
                            content_type=content_type,
                            response_time_ms=elapsed_ms,
                            content_hash="",
                            error=f"Response exceeded size limit: {content_length} bytes",
                        )
                except ValueError:
                    pass

            # 6. Read and decompress body with byte limit guard
            try:
                await response.aread()
                raw_bytes = response.content
                if len(raw_bytes) > self.max_response_size:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    return FetchResult(
                        url=current_url,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        content="",
                        content_type=content_type,
                        response_time_ms=elapsed_ms,
                        content_hash="",
                        error=f"Response body exceeded maximum limit of {self.max_response_size} bytes",
                    )
            finally:
                await response.aclose()

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            decoded_content = response.text
            content_hash = hashlib.sha256(raw_bytes).hexdigest()

            return FetchResult(
                url=current_url,
                status_code=response.status_code,
                headers=dict(response.headers),
                content=decoded_content,
                content_type=content_type,
                response_time_ms=elapsed_ms,
                content_hash=content_hash,
                redirected_urls=redirect_history,
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return FetchResult(
            url=current_url,
            status_code=0,
            headers={},
            content="",
            content_type="",
            response_time_ms=elapsed_ms,
            content_hash="",
            error=f"Exceeded maximum redirects limit of {self.max_redirects}",
        )
