import pytest
from app.extractors.linkedin import (
    LinkedInExtractor,
    parse_and_validate_linkedin_url,
)


def test_parse_and_validate_personal_profiles():
    # Standard personal profile
    res1 = parse_and_validate_linkedin_url("https://www.linkedin.com/in/satyanadella")
    assert res1 is not None
    clean_url, norm_url, category = res1
    assert clean_url == "https://www.linkedin.com/in/satyanadella"
    assert norm_url == "https://www.linkedin.com/in/satyanadella"
    assert category == "in"

    # Subdomain, trailing slash, mixed case
    res2 = parse_and_validate_linkedin_url("https://uk.linkedin.com/in/John-Doe-12345/")
    assert res2 is not None
    clean_url2, norm_url2, category2 = res2
    assert clean_url2 == "https://www.linkedin.com/in/John-Doe-12345"
    assert norm_url2 == "https://www.linkedin.com/in/john-doe-12345"
    assert category2 == "in"

    # With tracking queries
    res3 = parse_and_validate_linkedin_url("https://linkedin.com/in/alexsmith?miniProfileUrn=urn%3Ali&trk=people-guest")
    assert res3 is not None
    clean_url3, norm_url3, category3 = res3
    assert clean_url3 == "https://www.linkedin.com/in/alexsmith"
    assert norm_url3 == "https://www.linkedin.com/in/alexsmith"


def test_parse_and_validate_company_profiles():
    res = parse_and_validate_linkedin_url("https://www.linkedin.com/company/google/")
    assert res is not None
    clean_url, norm_url, category = res
    assert clean_url == "https://www.linkedin.com/company/google"
    assert norm_url == "https://www.linkedin.com/company/google"
    assert category == "company"


def test_reject_share_and_utility_urls():
    # Share buttons
    assert parse_and_validate_linkedin_url("https://www.linkedin.com/sharing/share-offsite/?url=https://example.com") is None
    assert parse_and_validate_linkedin_url("https://www.linkedin.com/shareArticle?mini=true&url=https://example.com") is None

    # Utility paths
    assert parse_and_validate_linkedin_url("https://www.linkedin.com/login") is None
    assert parse_and_validate_linkedin_url("https://www.linkedin.com/feed") is None
    assert parse_and_validate_linkedin_url("https://www.linkedin.com/jobs") is None
    assert parse_and_validate_linkedin_url("https://www.linkedin.com/help") is None

    # Bare domain / no slug
    assert parse_and_validate_linkedin_url("https://www.linkedin.com") is None
    assert parse_and_validate_linkedin_url("https://www.linkedin.com/in/") is None
    assert parse_and_validate_linkedin_url("https://www.linkedin.com/company") is None

    # Non-LinkedIn domains
    assert parse_and_validate_linkedin_url("https://twitter.com/in/alex") is None


def test_extract_from_text_nodes():
    nodes = [
        {
            "text": "Connect with our CEO on LinkedIn at https://www.linkedin.com/in/johndoe today.",
            "source_type": "body",
        },
        {
            "text": "Check our company page: linkedin.com/company/acme-corp",
            "source_type": "footer",
        },
    ]

    extracted = LinkedInExtractor.extract_from_nodes(nodes, attribute_contacts=[])
    norm_values = [item["normalized_value"] for item in extracted]

    assert "https://www.linkedin.com/in/johndoe" in norm_values
    assert "https://www.linkedin.com/company/acme-corp" in norm_values

    # Check context
    ceo_item = next(i for i in extracted if i["normalized_value"] == "https://www.linkedin.com/in/johndoe")
    assert "CEO on LinkedIn" in ceo_item["context"]


def test_extract_from_attribute_contacts():
    attributes = [
        {
            "type": "linkedin",
            "raw_value": "https://www.linkedin.com/in/JaneDoe?trk=profile",
            "source_type": "anchor",
            "context": "Jane Doe's Profile",
        },
        # Duplicate should be ignored
        {
            "type": "linkedin",
            "raw_value": "https://linkedin.com/in/janedoe/",
            "source_type": "anchor",
            "context": "LinkedIn",
        },
    ]

    extracted = LinkedInExtractor.extract_from_nodes(text_nodes=[], attribute_contacts=attributes)
    assert len(extracted) == 1
    assert extracted[0]["normalized_value"] == "https://www.linkedin.com/in/janedoe"
    assert extracted[0]["confidence"] >= 0.95
    assert extracted[0]["context"] == "Jane Doe's Profile"
