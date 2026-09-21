import re
import urllib.parse
from typing import List, Dict, Any, Optional, Set, Tuple

from app.extractors.context import extract_surrounding_context

# Matches LinkedIn profile URLs in text or attributes
# Supported types: /in/ (personal), /company/ (company/org), /school/ (educational institution)
LINKEDIN_URL_REGEX = re.compile(
    r"(?:https?://)?(?:[a-zA-Z0-9-]+\.)*linkedin\.com/"
    r"(in|company|school|showcase)/"
    r"([a-zA-Z0-9\-_%]+)/?",
    re.IGNORECASE,
)

# Reject keywords and utility paths that are NOT profiles
NON_PROFILE_PATHS = {
    "sharing",
    "sharearticle",
    "share-offsite",
    "login",
    "signup",
    "feed",
    "jobs",
    "learning",
    "help",
    "legal",
    "pulse",
    "posts",
    "newsletters",
    "events",
    "search",
    "checkpoint",
    "notifications",
    "messaging",
    "groups",
    "pub",
    "in",
    "company",
    "school",
}


def parse_and_validate_linkedin_url(raw_url: str) -> Optional[Tuple[str, str, str]]:
    """
    Parses, validates, and normalizes a candidate LinkedIn URL.
    Returns (clean_url, normalized_url, profile_type) or None if invalid.
    """
    if not raw_url:
        return None

    raw_url = raw_url.strip().strip(".,;:()[]{}<>\"'")

    # Ensure a scheme is present for urlparse
    parsed_input = raw_url
    if not parsed_input.startswith("http://") and not parsed_input.startswith("https://"):
        parsed_input = "https://" + parsed_input

    try:
        parsed = urllib.parse.urlparse(parsed_input)
    except Exception:
        return None

    hostname = (parsed.hostname or "").lower()
    if not hostname.endswith("linkedin.com"):
        return None

    # Strip query and fragments to isolate path
    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        return None

    category = parts[0].lower()
    if category not in ("in", "company", "school", "showcase"):
        return None

    slug = urllib.parse.unquote(parts[1]).strip()
    if not slug or slug.lower() in NON_PROFILE_PATHS:
        return None

    # Validate slug format (at least 2 chars, valid characters)
    if not re.match(r"^[a-zA-Z0-9\-_%]{2,100}$", slug):
        return None

    # Canonical URLs
    clean_url = f"https://www.linkedin.com/{category}/{slug}"
    normalized_url = f"https://www.linkedin.com/{category}/{slug.lower()}"

    return clean_url, normalized_url, category


def calculate_linkedin_confidence(source_type: str, is_contact_page: bool = False) -> float:
    """Compute confidence score based on source location and extraction context."""
    if source_type in ("header", "footer", "address"):
        return 0.98
    if source_type in ("anchor", "attribute"):
        return 0.95
    if is_contact_page:
        return 0.90
    return 0.85


class LinkedInExtractor:
    """
    Extracts, validates, normalizes, and scores LinkedIn profile URLs from HTML attributes and text.
    """

    @classmethod
    def extract_from_nodes(
        cls,
        text_nodes: List[Dict[str, Any]],
        attribute_contacts: List[Dict[str, Any]],
        is_contact_page: bool = False,
    ) -> List[Dict[str, Any]]:
        extracted: List[Dict[str, Any]] = []
        seen_normalized: Set[str] = set()

        # 1. Process explicit attribute contacts (from <a> tags)
        for attr in attribute_contacts:
            if attr.get("type") == "linkedin":
                raw = attr.get("raw_value", "").strip()
                result = parse_and_validate_linkedin_url(raw)
                if result:
                    clean_url, norm_url, category = result
                    if norm_url not in seen_normalized:
                        confidence = calculate_linkedin_confidence(
                            attr.get("source_type", "attribute"),
                            is_contact_page=is_contact_page,
                        )
                        context = attr.get("context") or clean_url
                        extracted.append({
                            "type": "linkedin",
                            "value": clean_url,
                            "normalized_value": norm_url,
                            "confidence": confidence,
                            "source_type": attr.get("source_type", "attribute"),
                            "context": context,
                        })
                        seen_normalized.add(norm_url)

        # 2. Process visible text nodes for LinkedIn URLs
        for node in text_nodes:
            text = node.get("text", "")
            source_type = node.get("source_type", "body")

            for match in LINKEDIN_URL_REGEX.finditer(text):
                raw_match = match.group(0)
                result = parse_and_validate_linkedin_url(raw_match)
                if result:
                    clean_url, norm_url, category = result
                    if norm_url not in seen_normalized:
                        context = extract_surrounding_context(text, raw_match)
                        confidence = calculate_linkedin_confidence(
                            source_type,
                            is_contact_page=is_contact_page,
                        )
                        extracted.append({
                            "type": "linkedin",
                            "value": clean_url,
                            "normalized_value": norm_url,
                            "confidence": confidence,
                            "source_type": source_type,
                            "context": context or clean_url,
                        })
                        seen_normalized.add(norm_url)

        return extracted
