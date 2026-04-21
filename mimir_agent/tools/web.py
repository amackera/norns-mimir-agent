import re

import httpx
from norns import tool


def _extract_text(html: str) -> str:
    """Extract readable text from HTML, stripping tags and collapsing whitespace."""
    # Remove script and style blocks
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities
    for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
        text = text.replace(entity, char)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_one(url: str) -> str:
    """Fetch a single URL and return its text content."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=15, headers={"User-Agent": "Mimir/1.0"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"Failed to fetch {url}: {e}"

    content_type = resp.headers.get("content-type", "")
    if "html" in content_type:
        text = _extract_text(resp.text)
    else:
        text = resp.text

    if len(text) > 8000:
        text = text[:8000] + f"\n\n... (truncated, {len(resp.text)} chars total)"
    return text


@tool
def read_url(urls: list[str]) -> str:
    """Fetch one or more web pages and extract their text content. Pass a list of URLs."""
    results = []
    for url in urls:
        text = _fetch_one(url)
        results.append(f"--- {url} ---\n{text}")
    if not results:
        return "No valid URLs found."
    return "\n\n".join(results)
