"""giga chat 자동완성 (/명령, @파일)."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.document import Document

from gigachanie.commands._chatcomplete import ChatCompleter


def _texts(root: Path, line: str, extra: list[str] | None = None) -> list[str]:
    c = ChatCompleter(root, extra or [])
    doc = Document(line, cursor_position=len(line))
    return [comp.text for comp in c.get_completions(doc, None)]


def test_슬래시_명령_완성(tmp_path: Path) -> None:
    out = _texts(tmp_path, "/co", ["mytask"])
    assert "compact" in out and "commands" in out
    assert "cost" in out


def test_커스텀_명령도_포함(tmp_path: Path) -> None:
    out = _texts(tmp_path, "/my", ["mytask", "other"])
    assert "mytask" in out


def test_슬래시는_첫단어에서만(tmp_path: Path) -> None:
    assert _texts(tmp_path, "고쳐줘 /co") == []


def test_at_파일_완성(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "util.py").write_text("y", encoding="utf-8")
    (tmp_path / "README.md").write_text("z", encoding="utf-8")

    top = _texts(tmp_path, "이 @")
    assert "src/" in top and "README.md" in top

    nested = _texts(tmp_path, "@src/m")
    assert nested == ["main.py"]


def test_at_숨김·무시_디렉터리_제외(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "keep.txt").write_text("k", encoding="utf-8")
    out = _texts(tmp_path, "@")
    assert "keep.txt" in out
    assert ".git/" not in out and "node_modules/" not in out


def test_at_루트밖_차단(tmp_path: Path) -> None:
    sub = tmp_path / "proj"
    sub.mkdir()
    assert _texts(sub, "@../") == []
