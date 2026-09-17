import logging
import re
from typing import List, Dict, Any, Set, Optional
import phonenumbers
from phonenumbers import PhoneNumberMatcher, PhoneNumberFormat

from app.extractors.context import extract_surrounding_context

logger = logging.getLogger(__name__)

# TLD to ISO country code mapping for default region inference
TLD_TO_REGION = {
    "uk": "GB",
    "co.uk": "GB",
    "us": "US",
    "ca": "CA",
    "in": "IN",
    "au": "AU",
    "de": "DE",
    "fr": "FR",
    "es": "ES",
    "it": "IT",
    "nl": "NL",
    "br": "BR",
    "jp": "JP",
}

# Regex to detect false positives (dates, sequential digits, timestamps)
DATE_REGEX = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$")
TIMESTAMP_REGEX = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
SEQUENTIAL_REGEX = re.compile(r"^(?:0123456789|1234567890|0987654321|9876543210)$")
REPEATED_DIGIT_REGEX = re.compile(r"^(\d)\1{6,}$")


def is_obvious_false_positive(raw_val: str) -> bool:
    """Checks if a string is a date, timestamp, or repetitive numeric sequence."""
    cleaned = re.sub(r"[^\d]", "", raw_val)
    if len(cleaned) < 7 or len(cleaned) > 15:
        return True

    if DATE_REGEX.match(raw_val.strip()):
        return True

    if TIMESTAMP_REGEX.match(raw_val.strip()):
        return True

    if SEQUENTIAL_REGEX.match(cleaned):
        return True

    if REPEATED_DIGIT_REGEX.match(cleaned):
        return True

    return False


def calculate_phone_confidence(
    source_type: str, has_international_prefix: bool, is_valid: bool, is_contact_page: bool
) -> float:
    if source_type == "tel":
        return 0.98
    if source_type == "address":
        return 0.92
    if has_international_prefix and is_valid:
        return 0.95
    if is_contact_page:
        return 0.90
    if is_valid:
        return 0.88
    return 0.75


class PhoneExtractor:
    """
    Extracts, validates, and normalizes phone numbers into E.164 representation.
    """

    @classmethod
    def get_default_region_for_domain(cls, domain: str) -> str:
        parts = domain.lower().split(".")
        if len(parts) >= 2:
            tld = parts[-1]
            if tld in TLD_TO_REGION:
                return TLD_TO_REGION[tld]
            if len(parts) >= 3:
                two_part = f"{parts[-2]}.{parts[-1]}"
                if two_part in TLD_TO_REGION:
                    return TLD_TO_REGION[two_part]
        return "US"

    @classmethod
    def extract_from_nodes(
        cls,
        text_nodes: List[Dict[str, Any]],
        attribute_contacts: List[Dict[str, Any]],
        domain: str = "",
        is_contact_page: bool = False,
    ) -> List[Dict[str, Any]]:
        extracted: List[Dict[str, Any]] = []
        seen_normalized: Set[str] = set()
        default_region = cls.get_default_region_for_domain(domain)

        # 1. Process tel: attribute contacts
        for attr in attribute_contacts:
            if attr.get("type") == "phone":
                raw = attr["raw_value"].strip()
                if is_obvious_false_positive(raw):
                    continue

                try:
                    parsed_phone = phonenumbers.parse(raw, default_region)
                    if phonenumbers.is_possible_number(parsed_phone):
                        is_valid = phonenumbers.is_valid_number(parsed_phone)
                        e164 = phonenumbers.format_number(
                            parsed_phone, PhoneNumberFormat.E164
                        )
                        region = phonenumbers.region_code_for_number(parsed_phone) or (
                            default_region if parsed_phone.country_code == 1 else None
                        )

                        if e164 not in seen_normalized:
                            confidence = calculate_phone_confidence(
                                source_type=attr.get("source_type", "tel"),
                                has_international_prefix=raw.startswith("+"),
                                is_valid=is_valid,
                                is_contact_page=is_contact_page,
                            )
                            extracted.append({
                                "type": "phone",
                                "value": raw,
                                "normalized_value": e164,
                                "country": region,
                                "confidence": confidence,
                                "source_type": attr.get("source_type", "tel"),
                                "context": attr.get("context", raw),
                            })
                            seen_normalized.add(e164)
                except Exception as e:
                    logger.debug("Error parsing tel: phone %s: %s", raw, e)

        # 2. Process visible text nodes using PhoneNumberMatcher
        for node in text_nodes:
            text = node["text"]
            source_type = node.get("source_type", "body")

            try:
                # Match against default region and international numbers with Leniency.POSSIBLE
                for match in PhoneNumberMatcher(
                    text, default_region, leniency=phonenumbers.Leniency.POSSIBLE
                ):
                    raw_phone = match.raw_string.strip()
                    if is_obvious_false_positive(raw_phone):
                        continue

                    phone_obj = match.number
                    if phonenumbers.is_possible_number(phone_obj):
                        is_valid = phonenumbers.is_valid_number(phone_obj)
                        e164 = phonenumbers.format_number(
                            phone_obj, PhoneNumberFormat.E164
                        )
                        region = phonenumbers.region_code_for_number(phone_obj) or (
                            default_region if phone_obj.country_code == 1 else None
                        )

                        if e164 not in seen_normalized:
                            has_plus = raw_phone.startswith("+")
                            confidence = calculate_phone_confidence(
                                source_type=source_type,
                                has_international_prefix=has_plus,
                                is_valid=is_valid,
                                is_contact_page=is_contact_page,
                            )
                            context = extract_surrounding_context(text, raw_phone)

                            extracted.append({
                                "type": "phone",
                                "value": raw_phone,
                                "normalized_value": e164,
                                "country": region,
                                "confidence": confidence,
                                "source_type": source_type,
                                "context": context or raw_phone,
                            })
                            seen_normalized.add(e164)
            except Exception as e:
                logger.debug("Error scanning text for phone numbers: %s", e)

        return extracted
