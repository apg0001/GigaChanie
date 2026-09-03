"""편집을 hunk(변경 덩어리) 단위로 쪼개고, 선택된 것만 적용한다.

승인 UI 에서 "이 hunk 만 받겠다"를 지원하기 위한 것.
`difflib.SequenceMatcher` 로 old→new 를 비교해 연속된 변경 구간을 하나의 hunk 로 본다.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class Hunk:
    old_start: int  # old 줄 인덱스 (0-based)
    old_lines: list[str]
    new_lines: list[str]

    def preview(self, context: int = 2) -> str:
        out: list[str] = []
        for ln in self.old_lines:
            out.append(f"- {ln}")
        for ln in self.new_lines:
            out.append(f"+ {ln}")
        return "\n".join(out) or "(빈 변경)"


def split_hunks(old: str, new: str) -> list[Hunk]:
    a = old.splitlines(keepends=True)
    b = new.splitlines(keepends=True)
    hunks: list[Hunk] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        hunks.append(Hunk(old_start=i1, old_lines=a[i1:i2], new_lines=b[j1:j2]))
    return hunks


def apply_selected(old: str, hunks: list[Hunk], accept: list[bool]) -> str:
    """accept[i] 가 True 인 hunk 만 적용한 새 내용을 만든다."""
    a = old.splitlines(keepends=True)
    result: list[str] = []
    cursor = 0
    for hunk, ok in zip(hunks, accept, strict=False):
        result.extend(a[cursor : hunk.old_start])
        result.extend(hunk.new_lines if ok else hunk.old_lines)
        cursor = hunk.old_start + len(hunk.old_lines)
    result.extend(a[cursor:])
    return "".join(result)
