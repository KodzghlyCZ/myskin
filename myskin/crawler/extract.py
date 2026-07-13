from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import html2text
from bs4 import BeautifulSoup
from pypdf import PdfReader

from myskin.crawler.urls import ParsedUrl, is_passthrough_url, normalize_url
from myskin.formats import DEFAULT_PASSTHROUGH_EXTENSIONS

logger = logging.getLogger(__name__)

_SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe"}
_LINK_ATTRS = ("href", "src")


@dataclass
class PageExtract:
    title: str
    markdown: str
    page_links: list[str]
    file_links: list[str]


def html_to_markdown(html: str) -> str:
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0
    converter.single_line_break = False
    return converter.handle(html).strip()


def extract_page(
    html: bytes,
    page_url: str,
    *,
    passthrough_extensions: frozenset[str] = DEFAULT_PASSTHROUGH_EXTENSIONS,
) -> PageExtract:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(_SKIP_TAGS):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)

    main = soup.find("main") or soup.find("article") or soup.body or soup
    markdown = html_to_markdown(str(main))

    page_links: list[str] = []
    file_links: list[str] = []
    seen: set[str] = set()

    for tag in soup.find_all(["a", "link"]):
        for attr in _LINK_ATTRS:
            href = tag.get(attr)
            if not href:
                continue
            parsed = normalize_url(href, page_url)
            if not parsed or parsed.normalized in seen:
                continue
            seen.add(parsed.normalized)
            if is_passthrough_url(parsed.normalized, passthrough_extensions):
                file_links.append(parsed.normalized)
            else:
                page_links.append(parsed.normalized)

    return PageExtract(
        title=title or page_url,
        markdown=markdown,
        page_links=sorted(page_links),
        file_links=sorted(file_links),
    )


def extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def file_title_from_url(url: ParsedUrl) -> str:
    segment = url.path.rsplit("/", 1)[-1]
    name = segment
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name.replace("-", " ").replace("_", " ").strip() or url.normalized


def pdf_title_from_url(url: ParsedUrl) -> str:
    return file_title_from_url(url)
