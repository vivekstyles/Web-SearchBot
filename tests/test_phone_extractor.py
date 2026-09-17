import pytest
from app.extractors.phone import PhoneExtractor, is_obvious_false_positive


def test_is_obvious_false_positive():
    assert is_obvious_false_positive("2026-09-17") is True
    assert is_obvious_false_positive("2024/12/31") is True
    assert is_obvious_false_positive("1234567890") is True
    assert is_obvious_false_positive("0000000000") is True
    assert is_obvious_false_positive("(555) 234-5678") is False
    assert is_obvious_false_positive("+1 555 234 5678") is False


def test_extract_us_phone():
    nodes = [
        {"text": "Call our hotline at (555) 234-5678 or 555-345-6789 today.", "source_type": "body"}
    ]
    extracted = PhoneExtractor.extract_from_nodes(nodes, attribute_contacts=[], domain="example.com")
    normalized = [p["normalized_value"] for p in extracted]

    assert "+15552345678" in normalized
    assert "+15553456789" in normalized
    assert extracted[0]["country"] == "US"


def test_extract_international_phone():
    nodes = [
        {"text": "UK branch: +44 20 7946 0958, India desk: +91 98765 43210", "source_type": "body"}
    ]
    extracted = PhoneExtractor.extract_from_nodes(nodes, attribute_contacts=[], domain="example.com")
    normalized = [p["normalized_value"] for p in extracted]

    assert "+442079460958" in normalized
    assert "+919876543210" in normalized


def test_extract_tel_attribute():
    attributes = [
        {
            "type": "phone",
            "raw_value": "+15559876543",
            "source_type": "tel",
            "context": "Call Us",
        }
    ]
    extracted = PhoneExtractor.extract_from_nodes(text_nodes=[], attribute_contacts=attributes, domain="example.com")
    assert len(extracted) == 1
    assert extracted[0]["normalized_value"] == "+15559876543"
    assert extracted[0]["confidence"] >= 0.95
