import asyncio
import socket
from unittest.mock import AsyncMock

import pytest

from backend.extractor import (
    ExtractionError,
    PublicResolver,
    SourcePage,
    parse_html,
    public_ip,
    related_links,
    validate_url,
)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://localhost", "http://127.0.0.1", "http://10.0.0.1",
    "http://169.254.169.254/latest/meta-data", "http://[::1]", "http://[::ffff:127.0.0.1]",
    "http://user:pass@example.com", "https://example.com:8080", "https://example.com\\@localhost",
    "http://something.internal", "http://machine.local", "https://facebook.com/post", "https://m.facebook.com/post",
    "https://example.com/\nfoo", "https://facebook.com./post",
])
def test_reject_unsafe_urls(url):
    with pytest.raises(ExtractionError):
        validate_url(url)


def test_valid_url_and_public_addresses():
    assert validate_url("https://example.org/program#section") == "https://example.org/program"
    assert public_ip("8.8.8.8")
    assert not public_ip("192.168.1.2")
    assert not public_ip("100.64.0.1")
    assert not public_ip("::ffff:127.0.0.1")


def test_resolver_checks_actual_dns_answers(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=records))
        with pytest.raises(OSError, match="non-public"):
            await PublicResolver().resolve("rebind.example", 443)
        records[0] = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        answers = await PublicResolver().resolve("public.example", 443)
        assert answers[0]["host"] == "8.8.8.8"
    asyncio.run(run())


def test_html_extracts_article_and_link_evidence():
    text = "Chương trình đào tạo kỹ năng số dành cho sinh viên, diễn ra vào tháng 12 năm 2026. " * 5
    html = f'<html><head><title>Khóa học</title></head><body><nav>Menu</nav><main><h1>Khóa học AI</h1><p>{text}</p><a href="/apply">Đăng ký</a></main><script>bad script</script></body></html>'
    page = parse_html(html, "https://example.org/course", "source_1")
    assert page.title == "Khóa học"
    assert "Chương trình" in page.text
    assert "bad script" not in page.text
    assert "https://example.org/apply" in page.text
    assert related_links(page) == ["https://example.org/apply"]


def test_related_links_are_bounded_and_same_host():
    page = SourcePage("source_1", "Program", "https://example.org/p", "Text", [
        {"title": "Apply now", "url": "https://external.example/apply"},
        {"title": "Privacy", "url": "https://example.org/privacy"},
        {"title": "Đối tượng và học phí", "url": "https://example.org/eligibility"},
        {"title": "Chi tiết chương trình", "url": "https://example.org/detail"},
        {"title": "Register", "url": "https://example.org/register"},
    ])
    links = related_links(page)
    assert len(links) == 2
    assert all(link.startswith("https://example.org/") and "privacy" not in link for link in links)
