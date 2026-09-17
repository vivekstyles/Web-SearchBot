import pytest
from app.crawler.sitemap import SitemapParser

URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page1</loc></url>
  <url><loc>https://example.com/page2</loc></url>
</urlset>
"""

INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sub_sitemap1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sub_sitemap2.xml</loc></sitemap>
</sitemapindex>
"""


def test_parse_urlset_sitemap():
    pages, sitemaps = SitemapParser.parse_sitemap_xml(URLSET_XML)
    assert len(pages) == 2
    assert "https://example.com/page1" in pages
    assert "https://example.com/page2" in pages
    assert len(sitemaps) == 0


def test_parse_sitemap_index():
    pages, sitemaps = SitemapParser.parse_sitemap_xml(INDEX_XML)
    assert len(pages) == 0
    assert len(sitemaps) == 2
    assert "https://example.com/sub_sitemap1.xml" in sitemaps
    assert "https://example.com/sub_sitemap2.xml" in sitemaps
