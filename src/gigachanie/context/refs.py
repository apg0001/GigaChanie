"""사용자 입력의 `@경로` 참조를 파일 내용으로 확장한다.

    "이 @src/foo.py 의 버그를 고쳐줘"
    → 원문 + 하단에 src/foo.py 내용 첨부

경로에 공백이 있으면 `@"경로 이름"` 처럼 따옴표로 감싼다.
"""

from __future__ import annotations

import re
from pathlib import Path

_REF_RE = re.compile(r"@(?:\"([^\"]+)\"|([^\s\"']+))")
_MAX_FILE_CHARS = 20_000
_MAX_TOTAL_CHARS = 60_000


def expand_file_refs(text: str, root: Path) -> tuple[str, list[str]]:
    """(확장된 입력, 첨부된 파일 상대경로 목록) 을 돌려준다."""
    root = root.resolve()
    seen: list[str] = []
    attachments: list[str] = []
    total = 0

    for m in _REF_RE.finditer(text):
        rel = m.group(1) or m.group(2)
        rel = rel.rstrip(".,;:)")
        if rel in seen:
            continue
        seen.append(rel)

        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            attachments.append(f"# @{rel}\n(작업 루트 밖의 경로 - 무시됨)")
            continue
        if not target.is_file():
            continue
        try:
            body = target.read_text("utf-8", errors="replace")
        except OSError as exc:
            attachments.append(f"# @{rel}\n(읽기 실패: {exc})")
            continue

        if len(body) > _MAX_FILE_CHARS:
            body = body[:_MAX_FILE_CHARS] + "\n…(잘림)"
        piece = f"# @{rel}\n```\n{body}\n```"
        if total + len(piece) > _MAX_TOTAL_CHARS:
            break
        attachments.append(piece)
        total += len(piece)

    if not attachments:
        return text, []

    expanded = text + "\n\n---\n참조된 파일:\n\n" + "\n\n".join(attachments)
    loaded = [s for s in seen if any(a.startswith(f"# @{s}\n```") for a in attachments)]
    return expanded, loaded
