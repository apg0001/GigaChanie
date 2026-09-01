"""장기 메모리 저장소 (메모리 하네스 2층).

`<root>/.agent/memory/` 에 낱개 마크다운 파일로 저장하고 `INDEX.md` 로 목차를 유지한다.
회수는 토큰 겹침 점수 기반(임베딩 미사용). 세션 시작 시 INDEX 를 컨텍스트에 주입하고,
에이전트는 `read_memory` 도구로 필요한 본문을 가져온다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

_MEMORY_DIRNAME = Path(".agent") / "memory"
_INDEX = "INDEX.md"
_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]+")
_MAX_INDEX_CHARS = 4000


def _slugify(title: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", title.strip().lower()).strip("-")
    return s or "memory"


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text) if len(t) > 1}


@dataclass
class MemoryEntry:
    slug: str
    title: str
    tags: list[str]
    created: str
    body: str
    path: Path

    @property
    def summary(self) -> str:
        for line in self.body.splitlines():
            if line.strip():
                return line.strip()
        return ""

    def score(self, query_tokens: set[str]) -> int:
        hay = _tokens(self.title) | _tokens(" ".join(self.tags)) | _tokens(self.body)
        return len(query_tokens & hay)


@dataclass
class MemoryStore:
    root: Path
    _dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self._dir = (self.root / _MEMORY_DIRNAME).resolve()

    # ------------------------------------------------------------------ 읽기

    @property
    def dir(self) -> Path:
        return self._dir

    def _parse(self, path: Path) -> MemoryEntry | None:
        try:
            raw = path.read_text("utf-8", errors="replace")
        except OSError:
            return None
        title, tags, created, body = path.stem, [], "", raw.strip()
        m = _FRONT_RE.match(raw)
        if m:
            front, body = m.group(1), m.group(2).strip()
            for line in front.splitlines():
                if ":" not in line:
                    continue
                key, _, val = line.partition(":")
                key, val = key.strip().lower(), val.strip()
                if key == "title":
                    title = val or title
                elif key == "tags":
                    tags = [t.strip() for t in val.strip("[]").split(",") if t.strip()]
                elif key == "created":
                    created = val
        return MemoryEntry(
            slug=path.stem, title=title, tags=tags, created=created, body=body, path=path
        )

    def all_entries(self) -> list[MemoryEntry]:
        if not self._dir.is_dir():
            return []
        entries = []
        for p in sorted(self._dir.glob("*.md")):
            if p.name == _INDEX:
                continue
            e = self._parse(p)
            if e is not None:
                entries.append(e)
        return entries

    def get(self, slug: str) -> MemoryEntry | None:
        p = self._dir / f"{slug}.md"
        return self._parse(p) if p.is_file() else None

    def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        qt = _tokens(query)
        scored = [(e.score(qt), e) for e in self.all_entries()]
        scored = [(s, e) for s, e in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def index_text(self) -> str:
        entries = self.all_entries()
        if not entries:
            return ""
        lines = ["장기 메모리 목록 (필요하면 read_memory 도구로 본문 조회):"]
        for e in entries:
            tag = f" [{', '.join(e.tags)}]" if e.tags else ""
            lines.append(f"- {e.slug}: {e.title}{tag} — {e.summary}")
        text = "\n".join(lines)
        return text[:_MAX_INDEX_CHARS]

    # ------------------------------------------------------------------ 쓰기

    def add(self, title: str, body: str, tags: list[str] | None = None) -> MemoryEntry:
        self._dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(title)
        candidate = slug
        i = 2
        while (self._dir / f"{candidate}.md").exists():
            candidate = f"{slug}-{i}"
            i += 1
        tags = tags or []
        front = (
            f"---\ntitle: {title}\ntags: [{', '.join(tags)}]\n"
            f"created: {date.today().isoformat()}\n---\n\n"
        )
        path = self._dir / f"{candidate}.md"
        path.write_text(front + body.strip() + "\n", encoding="utf-8")
        self._rebuild_index()
        return self._parse(path)  # type: ignore[return-value]

    def remove(self, slug: str) -> bool:
        p = self._dir / f"{slug}.md"
        if not p.is_file():
            return False
        p.unlink()
        self._rebuild_index()
        return True

    def _rebuild_index(self) -> None:
        entries = self.all_entries()
        lines = ["# 메모리 목차", ""]
        for e in entries:
            lines.append(f"- [{e.title}]({e.slug}.md) — {e.summary}")
        (self._dir / _INDEX).write_text("\n".join(lines) + "\n", encoding="utf-8")
