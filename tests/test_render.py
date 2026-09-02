"""마크다운 렌더링 테스트."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import gigachanie.render as render_module
from gigachanie.cli import app
from gigachanie.render import RenderError, parse_markdown, render

runner = CliRunner()

_MD = """\
# 분기 계획

## 목표
- 성능 개선
- 버그 정리

## 일정
1분기에 완료

```python
x = 1
```
"""


def test_parse_markdown() -> None:
    doc = parse_markdown(_MD)
    assert doc.title == "분기 계획"
    kinds = [b.kind for b in doc.blocks]
    assert "h1" in kinds and "h2" in kinds and "bullet" in kinds and "code" in kinds
    bullets = [b.text for b in doc.blocks if b.kind == "bullet"]
    assert bullets == ["성능 개선", "버그 정리"]


def test_render_md_passthrough(tmp_path: Path) -> None:
    out = render(_MD, tmp_path / "copy.md")
    assert out.read_text(encoding="utf-8") == _MD


def test_render_html(tmp_path: Path) -> None:
    out = render(_MD, tmp_path / "deck.html")
    html = out.read_text(encoding="utf-8")
    assert "<!doctype html>" in html.lower()
    assert "분기 계획" in html


def test_pandoc_html만_standalone_옵션_사용(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(render_module.subprocess, "run", fake_run)
    render_module._pandoc(tmp_path / "input.md", tmp_path / "output.html")
    render_module._pandoc(tmp_path / "input.md", tmp_path / "output.docx")

    assert "--standalone" in commands[0]
    assert "--standalone" not in commands[1]


def test_render_docx(tmp_path: Path) -> None:
    out = render(_MD, tmp_path / "plan.docx", prefer_pandoc=False)
    assert out.is_file() and out.stat().st_size > 0


def test_render_pptx_없으면_안내(tmp_path: Path) -> None:
    try:
        import pptx  # noqa: F401
    except ModuleNotFoundError:
        with pytest.raises(RenderError, match="python-pptx"):
            render(_MD, tmp_path / "d.pptx", prefer_pandoc=False)
    else:
        out = render(_MD, tmp_path / "d.pptx", prefer_pandoc=False)
        assert out.is_file()


def test_지원안하는_형식(tmp_path: Path) -> None:
    with pytest.raises(RenderError, match="지원하지 않는"):
        render(_MD, tmp_path / "x.xyz")


def test_giga_render_cli(tmp_path: Path) -> None:
    src = tmp_path / "in.md"
    src.write_text(_MD, encoding="utf-8")
    out = tmp_path / "out.html"
    result = runner.invoke(app, ["render", str(src), "-o", str(out)])
    assert result.exit_code == 0
    assert out.is_file()


def test_render_document_도구(tmp_path: Path) -> None:
    from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
    from gigachanie.loop.builtin_tools import build_registry
    from gigachanie.loop.tools import ToolContext
    from gigachanie.serving.base import run_sync

    tool = build_registry(writable=True).get("render_document")
    assert tool is not None
    ctx = ToolContext(root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO))
    res = run_sync(tool.run({"markdown": _MD, "path": "docs/plan.html"}, ctx))
    assert not res.is_error
    assert (tmp_path / "docs" / "plan.html").is_file()
