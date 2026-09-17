import re
from typing import List, Dict, Any, Set
from urllib.parse import unquote

from app.extractors.context import extract_surrounding_context

# Regex for standard RFC-style emails
STANDARD_EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9])?@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,63}\b"
)

# Obfuscation patterns: [at], (at), AT, [@], etc.
OBFUSCATED_PATTERNS = [
    # e.g., user [at] example [dot] com or user [@] example [.] com
    re.compile(
        r"\b([A-Za-z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\[@\]|@|\s+at\s+)\s*"
        r"([A-Za-z0-9.-]+)\s*(?:\[dot\]|\(dot\)|\[\.\]|\.|\s+dot\s+)\s*"
        r"([A-Za-z]{2,24})\b",
        re.IGNORECASE,
    ),
]

# File extensions that falsely look like emails e.g. logo@2x.png
INVALID_TLDS_AND_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico",
    "js", "css", "woff", "woff2", "ttf", "eot",
    "mp3", "mp4", "webm", "zip", "tar", "gz",
}


def is_valid_email_candidate(email: str) -> bool:
    """Verifies that an extracted email has a valid format and is not an asset filename."""
    if not email or "@" not in email:
        return False

    parts = email.split("@")
    if len(parts) != 2:
        return False

    local_part, domain_part = parts
    if not local_part or not domain_part:
        return False

    if "." not in domain_part:
        return False

    tld = domain_part.split(".")[-1].lower()
    if tld in INVALID_TLDS_AND_EXTENSIONS:
        return False

    if len(tld) < 2 or len(tld) > 24:
        return False

    return True


def calculate_email_confidence(source_type: str, is_obfuscated: bool = False, is_contact_page: bool = False) -> float:
    """Compute confidence score based on source location and extraction method."""
    if source_type == "mailto":
        return 0.99
    if source_type == "address":
        return 0.95
    if is_obfuscated:
        return 0.75
    if is_contact_page:
        return 0.90
    if source_type in ("header", "footer"):
        return 0.88
    return 0.85


class EmailExtractor:
    """
    Extracts, de-obfuscates, normalizes, and scores email addresses from HTML text and attributes.
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

        # 1. Process explicit mailto: attribute contacts
        for attr in attribute_contacts:
            if attr.get("type") == "email":
                raw = unquote(attr["raw_value"].strip())
                norm = raw.lower()
                if is_valid_email_candidate(norm):
                    confidence = calculate_email_confidence(
                        attr.get("source_type", "mailto"),
                        is_obfuscated=False,
                        is_contact_page=is_contact_page,
                    )
                    extracted.append({
                        "type": "email",
                        "value": raw,
                        "normalized_value": norm,
                        "confidence": confidence,
                        "source_type": attr.get("source_type", "mailto"),
                        "context": attr.get("context", raw),
                    })
                    seen_normalized.add(norm)

        # 2. Process visible text nodes
        for node in text_nodes:
            text = node["text"]
            source_type = node.get("source_type", "body")

            # A. Standard regex
            matches = STANDARD_EMAIL_REGEX.finditer(text)
            for match in matches:
                raw_email = match.group(0).strip(".,;:()[]{}<>\"'")
                norm = raw_email.lower()
                if norm not in seen_normalized and is_valid_email_candidate(norm):
                    context = extract_surrounding_context(text, raw_email)
                    confidence = calculate_email_confidence(
                        source_type,
                        is_obfuscated=False,
                        is_contact_page=is_contact_page,
                    )
                    extracted.append({
                        "type": "email",
                        "value": raw_email,
                        "normalized_value": norm,
                        "confidence": confidence,
                        "source_type": source_type,
                        "context": context or raw_email,
                    })
                    seen_normalized.add(norm)

            # B. Obfuscated regex patterns (e.g. hello [at] example [dot] com)
            for pattern in OBFUSCATED_PATTERNS:
                for match in pattern.finditer(text):
                    local, domain, tld = match.groups()
                    deobfuscated = f"{local}@{domain}.{tld}".strip()
                    norm = deobfuscated.lower()
                    if norm not in seen_normalized and is_valid_email_candidate(norm):
                        raw_match = match.group(0)
                        context = extract_surrounding_context(text, raw_match)
                        confidence = calculate_email_confidence(
                            source_type,
                            is_obfuscated=True,
                            is_contact_page=is_contact_page,
                        )
                        extracted.append({
                            "type": "email",
                            "value": raw_match,
                            "normalized_value": norm,
                            "confidence": confidence,
                            "source_type": source_type,
                            "context": context or raw_match,
                        })
                        seen_normalized.add(norm)

        return extracted
