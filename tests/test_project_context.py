"""프로젝트 컨텍스트 파일 로더 테스트."""

from pathlib import Path

from gigachanie.context.project_file import load_project_context


def test_컨텍스트_없으면_빈결과(tmp_path: Path) -> None:
    pc = load_project_context(tmp_path, include_global=False)
    assert not pc.found
    assert pc.text == ""


def test_AGENTS_md_로드(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# 프로젝트\n빌드: make", encoding="utf-8")
    pc = load_project_context(tmp_path, include_global=False)
    assert pc.found
    assert "빌드: make" in pc.text
    assert pc.sources[0].name == "AGENTS.md"


def test_우선순위_AGENTS_먼저(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("에이전트", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("클로드", encoding="utf-8")
    pc = load_project_context(tmp_path, include_global=False)
    assert len(pc.sources) == 1
    assert "에이전트" in pc.text
    assert "클로드" not in pc.text


def test_계층_병합_루트에서_하위로(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("루트 규칙", encoding="utf-8")
    sub = tmp_path / "packages" / "web"
    sub.mkdir(parents=True)
    (sub / "AGENTS.md").write_text("web 전용 규칙", encoding="utf-8")
    pc = load_project_context(tmp_path, sub, include_global=False)
    assert len(pc.sources) == 2
    assert pc.text.index("루트 규칙") < pc.text.index("web 전용 규칙")


def test_nested_context_파일_인식(tmp_path: Path) -> None:
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "context.md").write_text("숨은 컨텍스트", encoding="utf-8")
    pc = load_project_context(tmp_path, include_global=False)
    assert "숨은 컨텍스트" in pc.text
