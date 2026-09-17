import pytest
from app.extractors.context import extract_surrounding_context


def test_extract_surrounding_context():
    full = "If you have any questions regarding your invoice, please contact our billing department at billing@example.com for immediate help with your account."
    snippet = extract_surrounding_context(full, "billing@example.com", max_chars_before=40, max_chars_after=40)

    assert "billing@example.com" in snippet
    assert "billing department" in snippet
    assert "immediate help" in snippet


def test_extract_context_boundaries():
    full = "Short text hello@example.com end."
    snippet = extract_surrounding_context(full, "hello@example.com", max_chars_before=50, max_chars_after=50)
    assert snippet == "Short text hello@example.com end."
