import logging
import xml.etree.ElementTree as ET
from typing import List, Set, Optional, Callable, Awaitable, Tuple
from urllib.parse import urlparse

from app.crawler.url import normalize_url, is_same_domain, is_valid_crawlable_url

logger = logging.getLogger(__name__)


class SitemapParser:
    """
    Safely parses XML sitemaps and sitemap indexes to extract URLs for crawling.
    """

    @staticmethod
    def parse_sitemap_xml(xml_content: str) -> Tuple[List[str], List[str]]:
        """
        Parses sitemap XML and returns:
        - candidate page URLs found in <url><loc>
        - child sitemap URLs found in <sitemap><loc>
        """
        page_urls: List[str] = []
        child_sitemaps: List[str] = []

        if not xml_content or not xml_content.strip():
            return page_urls, child_sitemaps

        try:
            # Parse XML safely without resolving external entities
            root = ET.fromstring(xml_content.strip())
        except Exception as e:
            logger.warning("Failed to parse sitemap XML: %s", e)
            return page_urls, child_sitemaps

        # Remove XML namespaces from tag names: e.g. {http://www.sitemaps.org/schemas/sitemap/0.9}urlset -> urlset
        tag_name = root.tag.split("}")[-1] if "}" in root.tag else root.tag

        if tag_name == "sitemapindex":
            for sitemap in root:
                s_tag = sitemap.tag.split("}")[-1] if "}" in sitemap.tag else sitemap.tag
                if s_tag == "sitemap":
                    for elem in sitemap:
                        e_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if e_tag == "loc" and elem.text:
                            child_sitemaps.append(elem.text.strip())

        elif tag_name == "urlset":
            for url_elem in root:
                u_tag = url_elem.tag.split("}")[-1] if "}" in url_elem.tag else url_elem.tag
                if u_tag == "url":
                    for elem in url_elem:
                        e_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if e_tag == "loc" and elem.text:
                            page_urls.append(elem.text.strip())

        return page_urls, child_sitemaps

    @classmethod
    async def discover_urls_from_sitemaps(
        cls,
        sitemap_urls: List[str],
        fetcher_func: Callable[[str], Awaitable[Tuple[int, Optional[str]]]],
        allowed_domains: List[str],
        max_urls: int = 500,
        max_depth: int = 2,
    ) -> List[str]:
        """
        Fetches and extracts crawlable URLs from sitemaps, up to max_urls.
        """
        discovered: List[str] = []
        visited_sitemaps: Set[str] = set()
        sitemap_queue = [(url, 0) for url in sitemap_urls]

        while sitemap_queue and len(discovered) < max_urls:
            sitemap_url, depth = sitemap_queue.pop(0)
            if sitemap_url in visited_sitemaps or depth > max_depth:
                continue
            visited_sitemaps.add(sitemap_url)

            try:
                status, content = await fetcher_func(sitemap_url)
                if status != 200 or not content:
                    continue

                page_urls, child_sitemaps = cls.parse_sitemap_xml(content)

                # Process page URLs
                for raw_url in page_urls:
                    norm = normalize_url(raw_url)
                    if (
                        norm
                        and is_same_domain(norm, allowed_domains)
                        and is_valid_crawlable_url(norm)
                        and norm not in discovered
                    ):
                        discovered.append(norm)
                        if len(discovered) >= max_urls:
                            break

                # Enqueue child sitemaps
                for child_url in child_sitemaps:
                    if child_url not in visited_sitemaps and depth + 1 <= max_depth:
                        sitemap_queue.append((child_url, depth + 1))

            except Exception as e:
                logger.warning("Error fetching sitemap %s: %s", sitemap_url, e)

        return discovered
