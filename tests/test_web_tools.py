"""웹 도구 테스트 (httpx MockTransport, 실제 네트워크 없음)."""

from pathlib import Path

import httpx
import pytest

from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.tools import ToolContext, ToolError
from gigachanie.loop.web_tools import html_to_text, parse_ddg_html
from gigachanie.serving.base import run_sync

_PY_URL = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F"
_DDG_HTML = f"""
<html><body>
<div class="result results_links">
  <a class="result__a" href="{_PY_URL}">Python 3 문서</a>
  <a class="result__snippet">파이썬 표준 라이브러리 레퍼런스</a>
</div>
<div class="result results_links">
  <a class="result__a" href="https://example.com/x">예시</a>
  <a class="result__snippet">예시 스니펫</a>
</div>
</body></html>
"""


def test_parse_ddg_html_리다이렉트_해제() -> None:
    results = parse_ddg_html(_DDG_HTML)
    assert len(results) == 2
    assert results[0].url == "https://docs.python.org/3/"
    assert results[0].title == "Python 3 문서"
    assert "표준 라이브러리" in results[0].snippet
    assert results[1].url == "https://example.com/x"


def test_html_to_text_스크립트_제거() -> None:
    html = (
        "<html><head><style>x{}</style></head><body>"
        "<p>본문</p><script>bad()</script><p>둘째</p></body></html>"
    )
    text = html_to_text(html)
    assert "본문" in text and "둘째" in text
    assert "bad()" not in text and "x{}" not in text


def _ctx_with_client(tmp_path: Path, handler) -> ToolContext:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    pol = ApprovalPolicy(mode=ApprovalMode.FULL_AUTO, approver=None)
    ctx = ToolContext(root=tmp_path, policy=pol)
    ctx.scratch["http_client"] = client
    return ctx


def _run(name: str, args: dict, ctx: ToolContext):
    tool = build_registry(web=True).get(name)
    assert tool is not None
    return run_sync(tool.run(args, ctx))


def test_web_search_도구(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert "duckduckgo" in req.url.host
        return httpx.Response(200, text=_DDG_HTML)

    res = _run("web_search", {"query": "python docs"}, _ctx_with_client(tmp_path, handler))
    assert not res.is_error
    assert "docs.python.org" in res.content
    assert "1." in res.content


def test_web_fetch_도구_html_텍스트화(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body><h1>제목</h1><p>내용입니다</p></body></html>",
            headers={"content-type": "text/html"},
        )

    res = _run("web_fetch", {"url": "https://example.com"}, _ctx_with_client(tmp_path, handler))
    assert not res.is_error
    assert "제목" in res.content and "내용입니다" in res.content
    assert "<h1>" not in res.content


def test_web_fetch_비http_거부(tmp_path: Path) -> None:
    ctx = _ctx_with_client(tmp_path, lambda r: httpx.Response(200))
    with pytest.raises(ToolError):
        _run("web_fetch", {"url": "ftp://x/y"}, ctx)


def test_웹도구_기본_비활성() -> None:
    assert build_registry().get("web_search") is None
    assert build_registry(web=True).get("web_search") is not None


def test_network_승인_suggest모드_거부(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=""))
    client = httpx.AsyncClient(transport=transport)
    ctx = ToolContext(
        root=tmp_path,
        policy=ApprovalPolicy(mode=ApprovalMode.SUGGEST, approver=None),
    )
    ctx.scratch["http_client"] = client
    tool = build_registry(web=True).get("web_search")
    assert tool is not None
    res = run_sync(tool.run({"query": "x"}, ctx))
    assert res.is_error
    assert "거부" in res.content
