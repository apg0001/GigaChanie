"""웹 도구: web_search, web_fetch.

기본 검색 백엔드는 DuckDuckGo HTML(키 불필요). 환경변수로 대체 가능:
  GIGA_SEARCH_URL  : SearXNG 인스턴스 (예: https://searx.example/search) → JSON API 사용
  GIGA_SEARCH_API  : "searxng" 강제 지정 (선택)

웹 도구는 기본 비활성. `giga agent --web` / `giga chat --web` 또는 /web on 으로 켠다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from gigachanie.loop.approval import ApprovalRequest
from gigachanie.loop.tools import ToolContext, ToolError, ToolRegistry, ToolResult

_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
_UA = "Mozilla/5.0 (compatible; GigaChanie/0.1; +https://github.com/apg0001/GigaChanie)"
_MAX_FETCH_CHARS = 20_000
_MAX_RESULTS = 8


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


# ------------------------------------------------------------------ DDG 파싱


class _DDGParser(HTMLParser):
    """html.duckduckgo.com/html 결과 페이지에서 제목/URL/스니펫 추출."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._mode: str | None = None
        self._cur_url = ""
        self._cur_title: list[str] = []
        self._cur_snip: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._mode = "title"
            self._cur_url = _clean_ddg_url(a.get("href") or "")
            self._cur_title = []
        elif tag in ("a", "div") and "result__snippet" in classes:
            self._mode = "snippet"
            self._cur_snip = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._mode == "title":
            self._mode = None
        elif self._mode == "snippet" and tag in ("a", "div"):
            title = " ".join("".join(self._cur_title).split())
            snippet = " ".join("".join(self._cur_snip).split())
            if self._cur_url and title:
                self.results.append(
                    SearchResult(title=title, url=self._cur_url, snippet=snippet)
                )
            self._mode = None
            self._cur_url = ""

    def handle_data(self, data: str) -> None:
        if self._mode == "title":
            self._cur_title.append(data)
        elif self._mode == "snippet":
            self._cur_snip.append(data)


def _clean_ddg_url(href: str) -> str:
    """DDG 리다이렉트 링크(//duckduckgo.com/l/?uddg=...) 를 실제 URL 로."""
    if "uddg=" in href:
        parsed = urlparse(href if href.startswith("http") else "https:" + href)
        q = parse_qs(parsed.query)
        if "uddg" in q:
            return q["uddg"][0]
    if href.startswith("//"):
        return "https:" + href
    return href


def parse_ddg_html(html: str) -> list[SearchResult]:
    parser = _DDGParser()
    parser.feed(html)
    return parser.results


# ------------------------------------------------------------------ HTML→텍스트


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.parts.append(data)


def html_to_text(html: str) -> str:
    ex = _TextExtractor()
    ex.feed(html)
    text = "".join(ex.parts)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ------------------------------------------------------------------ 검색 실행


async def _searxng_search(client: httpx.AsyncClient, base: str, query: str) -> list[SearchResult]:
    resp = await client.get(
        base, params={"q": query, "format": "json"}, headers={"User-Agent": _UA}
    )
    resp.raise_for_status()
    data = resp.json()
    out: list[SearchResult] = []
    for item in data.get("results", [])[:_MAX_RESULTS]:
        out.append(
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
        )
    return out


async def _ddg_search(client: httpx.AsyncClient, query: str) -> list[SearchResult]:
    resp = await client.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={"User-Agent": _UA},
    )
    resp.raise_for_status()
    return parse_ddg_html(resp.text)[:_MAX_RESULTS]


def _make_client(ctx: ToolContext) -> httpx.AsyncClient:
    injected = ctx.scratch.get("http_client")
    if isinstance(injected, httpx.AsyncClient):
        return injected
    return httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)


async def _web_search(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    query = args.get("query") or args.get("q")
    if not query or not isinstance(query, str):
        raise ToolError("query 인자(문자열)가 필요합니다.")

    allowed, reason = ctx.policy.check(
        ApprovalRequest(kind="network", summary=f"웹 검색: {query}", detail=query)
    )
    if not allowed:
        return ToolResult.error(f"웹 검색 거부됨 ({reason})")

    searx = os.environ.get("GIGA_SEARCH_URL")
    client = _make_client(ctx)
    owns = ctx.scratch.get("http_client") is None
    try:
        if searx:
            results = await _searxng_search(client, searx, query)
        else:
            results = await _ddg_search(client, query)
    except httpx.HTTPError as exc:
        return ToolResult.error(f"검색 실패: {exc}")
    finally:
        if owns:
            await client.aclose()

    if not results:
        return ToolResult(content=f"'{query}' 검색 결과 없음")
    lines = [
        f"{i}. {r.title}\n   {r.url}\n   {r.snippet[:300]}"
        for i, r in enumerate(results, start=1)
    ]
    return ToolResult(content="\n".join(lines))


async def _web_fetch(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    url = args.get("url")
    if not url or not isinstance(url, str):
        raise ToolError("url 인자(문자열)가 필요합니다.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("http/https URL 만 지원합니다.")

    allowed, reason = ctx.policy.check(
        ApprovalRequest(kind="network", summary=f"웹 fetch: {url}", detail=url)
    )
    if not allowed:
        return ToolResult.error(f"웹 fetch 거부됨 ({reason})")

    client = _make_client(ctx)
    owns = ctx.scratch.get("http_client") is None
    try:
        resp = await client.get(url, headers={"User-Agent": _UA})
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return ToolResult.error(f"fetch 실패: {exc}")
    finally:
        if owns:
            await client.aclose()

    ctype = resp.headers.get("content-type", "")
    body = resp.text
    text = body if "text/plain" in ctype or "json" in ctype else html_to_text(body)
    truncated = len(text) > _MAX_FETCH_CHARS
    text = text[:_MAX_FETCH_CHARS]
    note = "\n\n…(잘림)" if truncated else ""
    return ToolResult(content=f"# {url}\n\n{text}{note}")


def register_web_tools(reg: ToolRegistry) -> None:
    reg.register_func(
        "web_search",
        "웹을 검색해 상위 결과(제목·URL·요약)를 돌려준다. 최신 정보나 라이브러리 문서 확인용.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        _web_search,
    )
    reg.register_func(
        "web_fetch",
        "URL 을 가져와 본문 텍스트를 돌려준다(HTML 은 텍스트만 추출).",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        _web_fetch,
    )
