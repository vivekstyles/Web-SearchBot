import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from bs4 import BeautifulSoup, Tag, NavigableString

from app.crawler.url import (
    normalize_url,
    is_same_domain,
    is_valid_crawlable_url,
    get_url_priority,
)

logger = logging.getLogger(__name__)

DISCARD_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe", "template"}


class ParsedHtmlDocument:
    def __init__(self, raw_html: str, url: str):
        self.raw_html = raw_html
        self.url = url
        self.soup = BeautifulSoup(raw_html, "lxml")
        self.title: Optional[str] = None
        self._extract_title()
        self._clean_tree()

    def _extract_title(self) -> None:
        title_tag = self.soup.find("title")
        if title_tag and title_tag.string:
            self.title = title_tag.string.strip()
        else:
            h1 = self.soup.find("h1")
            if h1:
                self.title = h1.get_text(strip=True)

    def _clean_tree(self) -> None:
        """Strip non-content elements to prevent false positives."""
        for tag_name in DISCARD_TAGS:
            for el in self.soup.find_all(tag_name):
                el.decompose()

    def get_links(
        self,
        allowed_domains: List[str],
        include_subdomains: bool = True,
        follow_external_links: bool = False,
        max_links: int = 200,
    ) -> List[Tuple[str, int]]:
        """
        Extracts, normalizes, and filters links from <a> and canonical tags.
        Returns a list of tuples: (normalized_url, priority_score)
        """
        seen_urls: Set[str] = set()
        candidates: List[Tuple[str, int]] = []

        # Canonical link
        canonical = self.soup.find("link", rel=lambda x: x and "canonical" in x.lower())
        if canonical and canonical.get("href"):
            norm = normalize_url(canonical["href"], base_url=self.url)
            if norm and is_valid_crawlable_url(norm):
                if follow_external_links or is_same_domain(
                    norm, allowed_domains, include_subdomains=include_subdomains
                ):
                    seen_urls.add(norm)
                    candidates.append((norm, get_url_priority(norm) + 10))

        # Anchor links
        for a_tag in self.soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href:
                continue

            norm = normalize_url(href, base_url=self.url)
            if not norm or norm in seen_urls:
                continue

            if not is_valid_crawlable_url(norm):
                continue

            # Scope check
            if not follow_external_links and not is_same_domain(
                norm, allowed_domains, include_subdomains=include_subdomains
            ):
                continue

            seen_urls.add(norm)
            priority = get_url_priority(norm)
            candidates.append((norm, priority))

            if len(candidates) >= max_links:
                break

        # Sort candidate links by priority descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def get_text_nodes_with_context(self) -> List[Dict[str, Any]]:
        """
        Collects visible text nodes along with their semantic source container
        (e.g., 'address', 'header', 'footer', 'body').
        """
        nodes = []
        for element in self.soup.find_all(string=True):
            if not isinstance(element, NavigableString):
                continue
            text = str(element).strip()
            if not text:
                continue

            # Determine source type by traversing parents
            source_type = "body"
            curr = element.parent
            while curr and isinstance(curr, Tag) and curr.name != "[document]":
                tag_name = curr.name.lower()
                if tag_name == "address":
                    source_type = "address"
                    break
                elif tag_name == "header":
                    source_type = "header"
                    break
                elif tag_name == "footer":
                    source_type = "footer"
                    break
                curr = curr.parent

            nodes.append({
                "text": text,
                "source_type": source_type,
                "element": element,
            })

        return nodes

    def get_attribute_contacts(self) -> List[Dict[str, Any]]:
        """
        Extracts contacts explicitly embedded in href attributes:
        - mailto: links
        - tel: links
        """
        attr_contacts = []

        for a_tag in self.soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            anchor_text = a_tag.get_text(strip=True)

            # mailto:
            if href.lower().startswith("mailto:"):
                email_part = href[7:].split("?")[0].strip()
                if email_part:
                    # Check parent for semantic container
                    source_type = "mailto"
                    if a_tag.find_parent("address"):
                        source_type = "address"
                    elif a_tag.find_parent("footer"):
                        source_type = "footer"

                    attr_contacts.append({
                        "type": "email",
                        "raw_value": email_part,
                        "source_type": source_type,
                        "context": anchor_text or f"mailto:{email_part}",
                    })

            # tel:
            elif href.lower().startswith("tel:"):
                tel_part = href[4:].split("?")[0].strip()
                if tel_part:
                    source_type = "tel"
                    if a_tag.find_parent("address"):
                        source_type = "address"
                    elif a_tag.find_parent("footer"):
                        source_type = "footer"

                    attr_contacts.append({
                        "type": "phone",
                        "raw_value": tel_part,
                        "source_type": source_type,
                        "context": anchor_text or f"tel:{tel_part}",
                    })

        return attr_contacts
