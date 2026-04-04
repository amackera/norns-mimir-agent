import time

from norns import tool

from mimir_agent import config

# Simple in-memory cache: {doc_id: (text, timestamp)}
_doc_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 300  # 5 minutes


def _get_service():
    if not config.GOOGLE_CREDENTIALS_PATH:
        raise ValueError("Google Docs integration is not configured (GOOGLE_CREDENTIALS_PATH missing)")

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        config.GOOGLE_CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/documents.readonly"],
    )
    return build("docs", "v1", credentials=creds)


def _extract_text(document: dict) -> str:
    """Extract plain text from a Google Docs document structure."""
    text_parts = []
    for element in document.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for elem in paragraph.get("elements", []):
            text_run = elem.get("textRun")
            if text_run:
                text_parts.append(text_run.get("content", ""))
    return "".join(text_parts)


def _fetch_doc_text(doc_id: str) -> str:
    """Fetch doc text with caching."""
    now = time.time()
    cached = _doc_cache.get(doc_id)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    service = _get_service()
    document = service.documents().get(documentId=doc_id).execute()
    title = document.get("title", "Untitled")
    text = f"# {title}\n\n{_extract_text(document)}"

    _doc_cache[doc_id] = (text, now)
    return text


@tool
def search_google_docs(query: str) -> str:
    """Search across connected Google Docs by keyword. Returns matching snippets with doc titles."""
    try:
        _get_service()  # validate credentials early
    except ValueError as e:
        return str(e)

    if not config.GOOGLE_DOC_IDS:
        return "No Google Docs configured. Set GOOGLE_DOC_IDS in your environment."

    query_lower = query.lower()
    results = []

    for doc_id in config.GOOGLE_DOC_IDS:
        try:
            text = _fetch_doc_text(doc_id)
            lines = text.split("\n")
            title = lines[0] if lines else doc_id

            matching_lines = [
                line.strip() for line in lines
                if query_lower in line.lower() and line.strip()
            ]

            if matching_lines:
                snippets = "\n".join(f"  - {line[:200]}" for line in matching_lines[:5])
                results.append(f"{title} (doc_id: {doc_id}):\n{snippets}")

        except Exception as e:
            results.append(f"Error reading doc {doc_id}: {e}")

    if not results:
        return f"No matches for '{query}' in connected Google Docs."

    return "\n\n".join(results)


@tool
def read_google_doc(doc_id: str) -> str:
    """Read the full content of a Google Doc by its document ID."""
    try:
        text = _fetch_doc_text(doc_id)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error reading doc {doc_id}: {e}"

    if len(text) > 8000:
        text = text[:8000] + "\n\n... (truncated)"
    return text
