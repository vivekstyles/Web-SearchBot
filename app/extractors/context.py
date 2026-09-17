import re
from typing import Optional


def extract_surrounding_context(
    full_text: str, target: str, max_chars_before: int = 80, max_chars_after: int = 80
) -> Optional[str]:
    """
    Extracts a clean snippet of text surrounding the target substring.
    """
    if not full_text or not target:
        return None

    # Find position of target
    pos = full_text.lower().find(target.lower())
    if pos == -1:
        # Normalize whitespace in full_text and try again
        cleaned_text = re.sub(r"\s+", " ", full_text).strip()
        pos = cleaned_text.lower().find(target.lower())
        if pos == -1:
            return re.sub(r"\s+", " ", full_text)[:200].strip()
        full_text = cleaned_text

    start = max(0, pos - max_chars_before)
    end = min(len(full_text), pos + len(target) + max_chars_after)

    snippet = full_text[start:end]

    # Clean whitespace and newlines
    snippet = re.sub(r"\s+", " ", snippet).strip()

    if start > 0:
        snippet = "..." + snippet
    if end < len(full_text):
        snippet = snippet + "..."

    return snippet[:300]
