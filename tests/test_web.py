import httpx
import pytest

from mimir_agent.tools.web import _extract_text, _fetch_one


class TestExtractText:
    def test_strips_tags(self):
        assert _extract_text("<p>hello</p>") == "hello"

    def test_removes_script_blocks(self):
        html = "<script>var x = 1;</script><p>content</p>"
        assert _extract_text(html) == "content"

    def test_removes_style_blocks(self):
        html = "<style>.x { color: red; }</style><p>content</p>"
        assert _extract_text(html) == "content"

    def test_decodes_html_entities(self):
        assert _extract_text("&amp; &lt; &gt; &quot; &#39;") == "& < > \" '"

    def test_collapses_whitespace(self):
        html = "<p>hello</p>   <p>world</p>"
        assert _extract_text(html) == "hello world"

    def test_empty_html(self):
        assert _extract_text("") == ""

    def test_nested_tags(self):
        html = "<div><ul><li>item 1</li><li>item 2</li></ul></div>"
        result = _extract_text(html)
        assert "item 1" in result
        assert "item 2" in result


class TestFetchOne:
    def test_success_html(self, monkeypatch):
        response = httpx.Response(
            200,
            text="<html><body><p>Hello world</p></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://example.com"),
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: response)
        result = _fetch_one("https://example.com")
        assert "Hello world" in result

    def test_success_plain_text(self, monkeypatch):
        response = httpx.Response(
            200,
            text="plain text content",
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", "https://example.com"),
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: response)
        assert _fetch_one("https://example.com") == "plain text content"

    def test_truncates_long_content(self, monkeypatch):
        long_text = "x" * 10000
        response = httpx.Response(
            200,
            text=long_text,
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", "https://example.com"),
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: response)
        result = _fetch_one("https://example.com")
        assert "truncated" in result
        assert len(result) < 10000

    def test_http_error(self, monkeypatch):
        def raise_error(*a, **kw):
            raise httpx.ConnectError("connection refused")
        monkeypatch.setattr(httpx, "get", raise_error)
        result = _fetch_one("https://bad.example.com")
        assert "Failed to fetch" in result
