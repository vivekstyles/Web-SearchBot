import asyncio
import ipaddress
import logging
import socket
from typing import Tuple, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cloud metadata endpoints and known dangerous ranges
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("169.254.169.254/32"),  # AWS/GCP/Azure Instance Metadata Service
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
]


def is_safe_ip(ip_str: str, allow_private: bool = False) -> bool:
    """
    Validates whether an IP address is safe to request.
    Blocks private, loopback, link-local, multicast, and cloud metadata addresses.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    # Explicit blocked metadata IPs
    for blocked_net in BLOCKED_IP_NETWORKS:
        if ip in blocked_net:
            return False

    if allow_private:
        # For testing purposes only: allow localhost and RFC 1918 addresses
        return True

    # Check for private, loopback, link-local, multicast, unspecified
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False

    return True


async def resolve_and_validate_host(
    hostname: str, allow_private: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Resolves hostname to IP addresses asynchronously and verifies that
    all resolved IPs are safe to connect to.
    Returns: (is_safe, error_reason)
    """
    # If hostname is already an IP address
    try:
        ipaddress.ip_address(hostname)
        if not is_safe_ip(hostname, allow_private=allow_private):
            return False, f"Direct connection to private/reserved IP {hostname} is forbidden."
        return True, None
    except ValueError:
        pass

    # Resolve domain via DNS
    loop = asyncio.get_running_loop()
    try:
        addr_info = await loop.getaddrinfo(
            hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except socket.gaierror as e:
        return False, f"DNS resolution failed for {hostname}: {str(e)}"
    except Exception as e:
        return False, f"Error resolving hostname {hostname}: {str(e)}"

    if not addr_info:
        return False, f"No IP addresses found for hostname {hostname}"

    for family, socktype, proto, canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        if not is_safe_ip(ip_str, allow_private=allow_private):
            return (
                False,
                f"SSRF guard: Hostname {hostname} resolved to unsafe IP {ip_str}",
            )

    return True, None
