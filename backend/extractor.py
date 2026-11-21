import asyncio
import ipaddress
import re
import socket
import unicodedata
from dataclasses import asdict, dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from bs4 import BeautifulSoup
from readability import Document

MAX_BYTES = 2_000_000
MAX_PAGE_CHARS = 22000
FACEBOOK_HOSTS = ("facebook.com", "fb.com", "fb.watch", "m.me")


class ExtractionError(Exception):
    pass


def public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_global
    except ValueError:
        return False


def validate_url(value: str) -> str:
    try:
        if re.search(r"[\x00-\x20\x7f\\]", value):
            raise ValueError
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            raise ValueError
        if parsed.port and parsed.port != (443 if parsed.scheme == "https" else 80):
            raise ValueError
        if host.lower() in {"localhost", "metadata.google.internal"} or host.lower().endswith(
            (".localhost", ".local", ".internal")
        ):
            raise ValueError
        if "%" in host:
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError from None
        else:
            if not public_ip(host):
                raise ValueError
        if any(host == fb or host.endswith("." + fb) for fb in FACEBOOK_HOSTS):
            raise ExtractionError("Với bài đăng Facebook, hãy chọn tab Facebook và dán nội dung bài đăng.")
        return urldefrag(value)[0]
    except ValueError:
        raise ExtractionError("Chỉ hỗ trợ URL HTTP/HTTPS công khai, không hỗ trợ địa chỉ nội bộ hoặc cổng tùy chỉnh.") from None


class PublicResolver(AbstractResolver):
    """Validate actual DNS answers at connection time, not just a prior lookup.

    aiohttp connects to the returned numeric addresses, preventing DNS rebinding
    between validation and the connection. Redirects go through the same checks.
    """

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        if not records or any(not public_ip(record[4][0]) for record in records):
            raise OSError("Blocked non-public destination")
        return [
            {"hostname": host, "host": address[0], "port": port,
             "family": address_family, "proto": proto,
             "flags": socket.AI_NUMERICHOST}
            for address_family, _, proto, _, address in records
        ]

    async def close(self):
        pass


@dataclass
class SourcePage:
    id: str
    title: str
    url: str | None
    text: str
    links: list[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def plain(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_html(html: str, url: str, source_id: str) -> SourcePage:
    soup = BeautifulSoup(html, "lxml")
    title = plain(soup.title.get_text()) if soup.title else "Thông tin chương trình"
    meta = soup.find("meta", attrs={"property": "og:title"})
    if meta and meta.get("content"):
        title = plain(meta["content"])
    links, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = urldefrag(urljoin(url, anchor["href"]))[0]
        label = plain(anchor.get_text(" "))
        if label and href.startswith(("http://", "https://")) and href not in seen:
            links.append({"title": label[:180], "url": href[:2048]})
            seen.add(href)
        if len(links) >= 150:
            break
    # JSON-LD often contains dates and prices absent from the article body.
    structured = [tag.get_text()[:5000] for tag in soup.find_all("script", type="application/ld+json")[:3]]
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        tag.decompose()
    try:
        main = BeautifulSoup(Document(str(soup)).summary(), "lxml")
        text = main.get_text("\n", strip=True)
    except Exception:
        text = ""
    if len(text) < 200:
        body = soup.find("main") or soup.find("article") or soup.body or soup
        text = body.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 100:
        raise ExtractionError("Trang không có đủ văn bản để đọc (có thể cần JavaScript hoặc đăng nhập). Hãy dán nội dung vào ô văn bản.")
    text = text[:MAX_PAGE_CHARS]
    if structured:
        text += "\n\nDữ liệu có cấu trúc của trang:\n" + "\n".join(structured)[:8000]
    # Retain exact URLs in source evidence rather than letting the model invent them.
    if links:
        text += "\n\nLiên kết trong trang:\n" + "\n".join(
            f"{item['title']}: {item['url']}" for item in links[:50]
        )[:8000]
    return SourcePage(source_id, title[:500], url, text, links)


async def fetch_page(session: aiohttp.ClientSession, url: str, source_id: str, allowed_host: str | None = None) -> SourcePage:
    current = validate_url(url)
    try:
        for _ in range(5):
            if allowed_host and urlsplit(current).hostname != allowed_host:
                raise ExtractionError("Trang liên quan chuyển hướng ra ngoài website nguồn.")
            # Do not automatically follow redirects to local or metadata endpoints.
            async with session.get(current, allow_redirects=False) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        break
                    current = validate_url(urljoin(current, location))
                    continue
                if response.status != 200:
                    raise ExtractionError(f"Website trả về lỗi HTTP {response.status}. Bạn có thể dán nội dung thay thế.")
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type and "text/plain" not in content_type:
                    raise ExtractionError("Chỉ hỗ trợ trang HTML/văn bản; chưa hỗ trợ PDF, ảnh hoặc tệp tải xuống.")
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(32768):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ExtractionError("Trang vượt giới hạn tải 2 MB. Hãy dùng trang chi tiết hoặc dán nội dung.")
                    chunks.append(chunk)
                data = b"".join(chunks)
                try:
                    html = data.decode(response.charset or "utf-8", errors="replace")
                except LookupError:
                    html = data.decode("utf-8", errors="replace")
                if "text/plain" in content_type:
                    if len(html.strip()) < 100:
                        raise ExtractionError("Trang không có đủ văn bản để đọc.")
                    return SourcePage(source_id, urlsplit(current).hostname or current, current, html[:MAX_PAGE_CHARS])
                return await asyncio.to_thread(parse_html, html, current, source_id)
        raise ExtractionError("Website chuyển hướng quá nhiều lần.")
    except (aiohttp.ClientError, OSError, TimeoutError):
        raise ExtractionError("Không thể kết nối an toàn tới website hoặc trang đã hết thời gian chờ. Hãy thử link khác hoặc dán nội dung.") from None


def related_links(page: SourcePage) -> list[str]:
    host = urlsplit(page.url or "").hostname
    positive = ("program", "admission", "apply", "eligib", "scholarship", "deadline", "register", "detail", "hoc bong", "dang ky", "doi tuong", "thoi gian", "chi tiet", "chuong trinh", "tuyen sinh", "hoc phi")
    negative = ("privacy", "login", "logout", "terms", "cookie", "chinh sach", "bao mat")
    ranked = []
    for link in page.links:
        if urlsplit(link["url"]).hostname != host or link["url"] == page.url:
            continue
        text = unicodedata.normalize("NFKD", link["title"] + " " + urlsplit(link["url"]).path).lower()
        text = "".join(char for char in text if not unicodedata.combining(char)).replace("đ", "d")
        if any(word in text for word in negative):
            continue
        score = sum(word in text for word in positive)
        if score:
            ranked.append((score, link["url"]))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return list(dict.fromkeys(url for _, url in ranked))[:2]


async def extract_website(url: str, follow_related: bool) -> tuple[list[SourcePage], list[str]]:
    validate_url(url)
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), limit=3, limit_per_host=2)
    warnings = []
    try:
        async with asyncio.timeout(65), aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=20, connect=8),
            headers={"User-Agent": "ContentStudio/1.0 (public program information reader)", "Accept": "text/html,text/plain"},
            trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(),
        ) as session:
            main = await fetch_page(session, url, "source_1")
            pages = [main]
            if follow_related:
                for related in related_links(main):
                    try:
                        page = await fetch_page(session, related, f"source_{len(pages) + 1}", urlsplit(main.url).hostname)
                        if page.url not in {old.url for old in pages}:
                            pages.append(page)
                    except ExtractionError:
                        warnings.append("Không đọc được một trang liên quan; bài viết chỉ sử dụng các nguồn đã đọc thành công.")
            return pages, list(dict.fromkeys(warnings))
    except TimeoutError:
        raise ExtractionError("Quá thời gian đọc website. Hãy thử lại hoặc dán nội dung.") from None


def pasted_source(text: str) -> list[SourcePage]:
    title = next((line.strip() for line in text.splitlines() if line.strip()), "Nội dung đã dán")
    return [SourcePage("source_1", title[:160], None, text)]
