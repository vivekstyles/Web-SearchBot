import pytest
from app.crawler.security import is_safe_ip, resolve_and_validate_host


def test_is_safe_ip_loopback():
    assert is_safe_ip("127.0.0.1", allow_private=False) is False
    assert is_safe_ip("::1", allow_private=False) is False
    assert is_safe_ip("127.0.0.1", allow_private=True) is True


def test_is_safe_ip_private_rfc1918():
    assert is_safe_ip("10.0.0.1", allow_private=False) is False
    assert is_safe_ip("172.16.0.1", allow_private=False) is False
    assert is_safe_ip("192.168.1.100", allow_private=False) is False
    assert is_safe_ip("192.168.1.100", allow_private=True) is True


def test_is_safe_ip_cloud_metadata():
    # Cloud metadata is blocked even if allow_private is True!
    assert is_safe_ip("169.254.169.254", allow_private=False) is False
    assert is_safe_ip("169.254.169.254", allow_private=True) is False


def test_is_safe_ip_public():
    assert is_safe_ip("8.8.8.8", allow_private=False) is True
    assert is_safe_ip("1.1.1.1", allow_private=False) is True


@pytest.mark.asyncio
async def test_resolve_and_validate_host_rejection():
    # Direct private IP
    safe, reason = await resolve_and_validate_host("127.0.0.1", allow_private=False)
    assert safe is False
    assert "Direct connection to private/reserved IP" in reason

    # Localhost resolution
    safe, reason = await resolve_and_validate_host("localhost", allow_private=False)
    assert safe is False
    assert "SSRF guard" in reason or "Direct connection" in reason
