import pytest
from app.crawler.url import (
    normalize_url,
    get_domain,
    is_same_domain,
    is_valid_crawlable_url,
    get_url_priority,
)


def test_normalize_relative_url():
    base = "https://example.com/about/team"
    rel = "../contact"
    assert normalize_url(rel, base_url=base) == "https://example.com/contact"


def test_strip_fragments():
    url = "https://example.com/contact#team-section"
    assert normalize_url(url) == "https://example.com/contact"


def test_strip_default_ports():
    assert normalize_url("http://example.com:80/home") == "http://example.com/home"
    assert normalize_url("https://example.com:443/home") == "https://example.com/home"


def test_strip_trailing_slash():
    assert normalize_url("https://example.com/contact/") == "https://example.com/contact"
    # Root slash must be preserved
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_strip_tracking_parameters():
    url = "https://example.com/products?utm_source=twitter&id=42&fbclid=12345&category=books"
    normalized = normalize_url(url)
    assert "utm_source" not in normalized
    assert "fbclid" not in normalized
    assert "category=books" in normalized
    assert "id=42" in normalized
    # Query parameters are sorted deterministically
    assert normalized == "https://example.com/products?category=books&id=42"


def test_get_domain():
    assert get_domain("https://sub.example.com:8080/path") == "sub.example.com"
    assert get_domain("http://example.org/") == "example.org"


def test_is_same_domain():
    allowed = ["example.com"]
    assert is_same_domain("https://example.com/page", allowed, include_subdomains=True) is True
    assert is_same_domain("https://blog.example.com/page", allowed, include_subdomains=True) is True
    assert is_same_domain("https://blog.example.com/page", allowed, include_subdomains=False) is False
    assert is_same_domain("https://other.org/page", allowed) is False


def test_is_valid_crawlable_url():
    assert is_valid_crawlable_url("https://example.com/about") is True
    assert is_valid_crawlable_url("https://example.com/about.html") is True
    assert is_valid_crawlable_url("https://example.com/image.png") is False
    assert is_valid_crawlable_url("https://example.com/app.zip") is False


def test_get_url_priority():
    contact_prio = get_url_priority("https://example.com/contact-us")
    general_prio = get_url_priority("https://example.com/articles/2026/01/post")
    assert contact_prio > general_prio
