"""`giga chat` 입력 자동완성: `/명령` 과 `@파일`."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

_SLASH = [
    "help", "tools", "model", "mode", "write", "web", "remember", "memory",
    "compact", "undo", "diff", "ps", "commands", "cost", "clear", "steps",
    "info", "exit", "quit",
]

_IGNORE = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", "dist", "build", ".agent",
}


class ChatCompleter(Completer):
    def __init__(self, root: Path, extra_slash: Iterable[str] = ()) -> None:
        self._root = root
        self._slash = sorted({*_SLASH, *extra_slash})

    def get_completions(
        self, document: Document, complete_event: object
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        word = text.rsplit(" ", 1)[-1] if " " in text else text

        if word.startswith("/") and " " not in text:
            frag = word[1:]
            for name in self._slash:
                if name.startswith(frag):
                    yield Completion(name, start_position=-len(frag))
            return

        if word.startswith("@"):
            yield from self._files(word[1:])

    def _files(self, frag: str) -> Iterator[Completion]:
        frag = frag.replace("\\", "/")
        sub, _, leaf = frag.rpartition("/")
        base = (self._root / sub).resolve() if sub else self._root
        if self._root not in base.parents and base != self._root:
            return
        if not base.is_dir():
            return
        try:
            entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        for p in entries[:200]:
            if p.name.startswith(".") and not leaf.startswith("."):
                continue
            if p.name in _IGNORE:
                continue
            if not p.name.lower().startswith(leaf.lower()):
                continue
            disp = p.name + ("/" if p.is_dir() else "")
            yield Completion(disp, start_position=-len(leaf))
