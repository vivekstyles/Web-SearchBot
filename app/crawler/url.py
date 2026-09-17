import posixpath
import re
from urllib.parse import (
    urlparse,
    urlunparse,
    urljoin,
    parse_qsl,
    urlencode,
    unquote,
)
from typing import Optional, List, Set, Tuple

# Default tracking parameters to strip during normalization
DEFAULT_DENIED_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}

# Ignored extensions that are static non-HTML assets
STATIC_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".tiff",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".wmv", ".webm",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2",
    ".exe", ".dmg", ".app", ".deb", ".rpm", ".apk",
    ".css", ".js", ".mjs", ".woff", ".woff2", ".ttf", ".eot",
    ".json",
}

# Keywords indicating likely contact or team pages
CONTACT_PATH_KEYWORDS = [
    "contact",
    "contact-us",
    "contact_us",
    "contacts",
    "about",
    "about-us",
    "about_us",
    "team",
    "our-team",
    "company",
    "support",
    "help",
    "customer-service",
    "reach-us",
    "location",
    "staff",
    "people",
]


def normalize_url(
    url: str,
    base_url: Optional[str] = None,
    denied_params: Optional[Set[str]] = None,
) -> Optional[str]:
    """
    Normalizes a URL:
    - Resolves relative URLs against base_url
    - Strips URL fragments (#hash)
    - Lowercases scheme and netloc
    - Strips default ports (:80 for http, :443 for https)
    - Cleans duplicate path slashes and normalizes trailing slashes
    - Strips tracking query parameters and sorts query parameters
    - Ensures valid http/https scheme
    """
    if not url:
        return None

    url = url.strip()

    # Reject mailto:, tel:, javascript:, etc., from crawl normalization
    if url.startswith(("mailto:", "tel:", "javascript:", "data:", "sms:", "callto:")):
        return None

    # Resolve relative URL if base_url is provided
    if base_url:
        try:
            url = urljoin(base_url, url)
        except Exception:
            return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return None

    netloc = parsed.netloc.lower()
    if not netloc:
        return None

    # Remove default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Normalize path
    path = parsed.path
    if not path:
        path = "/"
    else:
        # Collapse multiple slashes: e.g. //contact -> /contact
        path = re.sub(r"/+", "/", path)
        # Handle trailing slash: remove trailing slash if path != '/'
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]

    # Normalize query parameters
    denied = denied_params if denied_params is not None else DEFAULT_DENIED_QUERY_PARAMS
    clean_query = ""
    if parsed.query:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
        filtered_pairs = [
            (k, v) for k, v in query_pairs if k.lower() not in denied
        ]
        # Sort parameters for deterministic caching and deduplication
        filtered_pairs.sort(key=lambda x: (x[0], x[1]))
        if filtered_pairs:
            clean_query = urlencode(filtered_pairs)

    # Reconstruct normalized URL (fragment omitted)
    normalized = urlunparse((scheme, netloc, path, "", clean_query, ""))
    return normalized


def get_domain(url: str) -> str:
    """Extract the hostname/domain from a URL."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if ":" in netloc:
        netloc = netloc.split(":")[0]
    return netloc


def is_same_domain(url: str, allowed_domains: List[str], include_subdomains: bool = True) -> bool:
    """
    Check if a URL belongs to the allowed domains list.
    If include_subdomains=True, 'sub.example.com' matches 'example.com'.
    """
    domain = get_domain(url)
    if not domain:
        return False

    for allowed in allowed_domains:
        allowed = allowed.lower()
        if ":" in allowed:
            allowed = allowed.split(":")[0]

        if domain == allowed:
            return True

        if include_subdomains and domain.endswith("." + allowed):
            return True

    return False


def is_valid_crawlable_url(url: str) -> bool:
    """Check if URL points to a likely HTML document rather than a static asset."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Check extension
    for ext in STATIC_EXTENSIONS:
        if path.endswith(ext):
            return False

    return True


def get_url_priority(url: str) -> int:
    """
    Score the priority of a URL for queue scheduling.
    Higher score means higher priority (e.g. contact pages crawled first).
    """
    parsed = urlparse(url)
    path_lower = parsed.path.lower()

    # Contact-specific pages get highest priority
    for kw in CONTACT_PATH_KEYWORDS:
        if kw in path_lower:
            return 100

    # Shallow paths preferred over deep paths
    segments = [s for s in path_lower.strip("/").split("/") if s]
    depth_penalty = min(len(segments) * 5, 40)

    return max(50 - depth_penalty, 1)


def is_likely_contact_url(url: str) -> Tuple[bool, int]:
    """
    Checks if a URL path matches contact, about, or team keywords.
    Returns: (is_contact_page, priority_score)
    """
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    for kw in CONTACT_PATH_KEYWORDS:
        if kw in path_lower:
            return True, 100
    return False, get_url_priority(url)
