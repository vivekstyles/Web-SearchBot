import pytest
from app.crawler.robots import DomainRobots


ROBOTS_SAMPLE = """User-agent: *
Disallow: /admin/
Disallow: /private/
Allow: /admin/public
Crawl-delay: 2.5
Sitemap: https://example.com/sitemap.xml
Sitemap: https://example.com/sitemap2.xml

User-agent: BadBot
Disallow: /
"""


def test_robots_allowed_and_disallowed():
    robots = DomainRobots("example.com", ROBOTS_SAMPLE)

    assert robots.is_allowed("ContactDiscoveryBot", "https://example.com/about") is True
    assert robots.is_allowed("ContactDiscoveryBot", "https://example.com/admin/settings") is False
    assert robots.is_allowed("ContactDiscoveryBot", "https://example.com/admin/public") is True
    assert robots.is_allowed("ContactDiscoveryBot", "https://example.com/private/data") is False


def test_robots_bad_bot_blocked():
    robots = DomainRobots("example.com", ROBOTS_SAMPLE)
    assert robots.is_allowed("BadBot", "https://example.com/about") is False


def test_robots_crawl_delay():
    robots = DomainRobots("example.com", ROBOTS_SAMPLE)
    assert robots.crawl_delay == 2.5


def test_robots_sitemaps():
    robots = DomainRobots("example.com", ROBOTS_SAMPLE)
    assert "https://example.com/sitemap.xml" in robots.sitemaps
    assert "https://example.com/sitemap2.xml" in robots.sitemaps


def test_empty_robots_allows_everything():
    robots = DomainRobots("example.com", "")
    assert robots.is_allowed("ContactDiscoveryBot", "https://example.com/any/path") is True
    assert robots.crawl_delay == 0.0
