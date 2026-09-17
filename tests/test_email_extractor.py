import pytest
from app.extractors.email import EmailExtractor, is_valid_email_candidate


def test_is_valid_email_candidate():
    assert is_valid_email_candidate("hello@example.com") is True
    assert is_valid_email_candidate("sales@example.co.uk") is True
    assert is_valid_email_candidate("john.doe+tag@sub.domain.org") is True
    # Assets / false positives
    assert is_valid_email_candidate("image@2x.png") is False
    assert is_valid_email_candidate("icon@3x.jpg") is False
    assert is_valid_email_candidate("user@localhost") is False
    assert is_valid_email_candidate("no-at-sign.com") is False


def test_extract_from_text_nodes():
    nodes = [
        {"text": "Feel free to write us at support@example.com anytime.", "source_type": "body"},
        {"text": "Inquiries: sales.team@example.co.uk or founder@example.com", "source_type": "header"},
    ]
    extracted = EmailExtractor.extract_from_nodes(nodes, attribute_contacts=[])
    values = [e["normalized_value"] for e in extracted]

    assert "support@example.com" in values
    assert "sales.team@example.co.uk" in values
    assert "founder@example.com" in values


def test_extract_obfuscated_emails():
    nodes = [
        {"text": "Reach our engineer at dev [at] example [dot] com for code help.", "source_type": "body"},
        {"text": "Contact info: security(at)example(dot)org", "source_type": "body"},
    ]
    extracted = EmailExtractor.extract_from_nodes(nodes, attribute_contacts=[])
    values = [e["normalized_value"] for e in extracted]

    assert "dev@example.com" in values
    assert "security@example.org" in values

    # Obfuscated confidence is adjusted
    dev_item = next(e for e in extracted if e["normalized_value"] == "dev@example.com")
    assert dev_item["confidence"] <= 0.80


def test_extract_mailto_attributes():
    attributes = [
        {
            "type": "email",
            "raw_value": "hello%2Btag@example.com",
            "source_type": "mailto",
            "context": "Email us",
        }
    ]
    extracted = EmailExtractor.extract_from_nodes(text_nodes=[], attribute_contacts=attributes)
    assert len(extracted) == 1
    assert extracted[0]["normalized_value"] == "hello+tag@example.com"
    assert extracted[0]["confidence"] >= 0.95
