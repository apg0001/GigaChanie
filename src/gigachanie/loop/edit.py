"""SEARCH/REPLACE 편집 엔진.

소형 오픈모델은 통짜 unified diff 생성이 불안정하므로, 검색 텍스트와 교체 텍스트를
명시하는 방식을 기본으로 한다. 매칭은 정확 → 줄 끝 공백 무시 → 들여쓰기 유연 순으로
단계적으로 시도한다.

텍스트 블록 형식(붙여넣기/프롬프트형 모델용):

    path/to/file.py
    <<<<<<< SEARCH
    (기존 코드)
    =======
    (새 코드)
    >>>>>>> REPLACE
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_HEAD = re.compile(r"^<{5,9} SEARCH\s*$")
_SEP = re.compile(r"^={5,9}\s*$")
_TAIL = re.compile(r"^>{5,9} REPLACE\s*$")
_FENCE = re.compile(r"^```[\w.+-]*\s*$")


class EditError(Exception):
    """편집 실패 (모델에 피드백)."""


class MatchMethod(str, Enum):
    EXACT = "exact"
    NEWLINE = "newline-normalized"
    RSTRIP = "line-rstrip"
    REINDENT = "reindent"
    CREATE = "create"


@dataclass(frozen=True)
class EditBlock:
    path: str
    search: str
    replace: str


@dataclass(frozen=True)
class EditApplication:
    new_content: str
    method: MatchMethod
    start_line: int  # 1-indexed, 교체가 일어난 첫 행 (create 면 0)
    replaced: int = 1  # 바뀐 위치 수 (replace_all 일 때 > 1)


# ---------------------------------------------------------------- 블록 파싱


def parse_edit_blocks(text: str) -> list[EditBlock]:
    """SEARCH/REPLACE 텍스트에서 편집 블록들을 추출한다."""
    lines = text.splitlines()
    blocks: list[EditBlock] = []
    i = 0
    n = len(lines)
    last_path: str | None = None

    while i < n:
        line = lines[i]
        if _HEAD.match(line):
            # 직전의 비어있지 않은 줄에서 경로를 찾는다 (펜스는 건너뜀)
            path = _lookback_path(lines, i) or last_path
            if not path:
                raise EditError("SEARCH 블록 앞에서 파일 경로를 찾지 못했습니다.")
            search_lines: list[str] = []
            i += 1
            while i < n and not _SEP.match(lines[i]):
                if _HEAD.match(lines[i]) or _TAIL.match(lines[i]):
                    raise EditError("SEARCH 블록에서 ======= 구분선을 만나기 전에 끝났습니다.")
                search_lines.append(lines[i])
                i += 1
            if i >= n:
                raise EditError("======= 구분선을 찾지 못했습니다.")
            i += 1  # skip separator
            replace_lines: list[str] = []
            while i < n and not _TAIL.match(lines[i]):
                if _HEAD.match(lines[i]):
                    raise EditError("REPLACE 종료선 전에 새 SEARCH 블록이 시작되었습니다.")
                replace_lines.append(lines[i])
                i += 1
            if i >= n:
                raise EditError(">>>>>>> REPLACE 종료선을 찾지 못했습니다.")
            i += 1  # skip tail
            last_path = path
            blocks.append(
                EditBlock(
                    path=path,
                    search="\n".join(search_lines),
                    replace="\n".join(replace_lines),
                )
            )
        else:
            i += 1

    if not blocks:
        raise EditError("SEARCH/REPLACE 블록을 찾지 못했습니다.")
    return blocks


def _lookback_path(lines: list[str], head_idx: int) -> str | None:
    j = head_idx - 1
    while j >= 0:
        raw = lines[j]
        stripped = raw.strip()
        if not stripped or _FENCE.match(raw):
            j -= 1
            continue
        # 직전 줄이 다른 편집 블록의 마커면 경로 정보가 없는 것 → 상속하도록 None
        if _TAIL.match(raw) or _SEP.match(raw) or _HEAD.match(raw):
            return None
        candidate = stripped.strip("`").strip()
        if not candidate:
            return None
        # 공백 없는 한 토큰이면 경로로 본다
        if " " not in candidate and len(candidate) <= 200:
            return candidate
        # "파일:" 같은 접두어가 붙은 경우 마지막 토큰
        return candidate.split()[-1]
    return None


# ---------------------------------------------------------------- 적용


def apply_edit(
    content: str,
    search: str,
    replace: str,
    *,
    file_exists: bool,
    replace_all: bool = False,
) -> EditApplication:
    """content 에 search→replace 를 적용한 새 내용을 만든다.

    search 가 비어 있으면: 파일이 없으면 새로 만들고(replace 가 전체 내용),
    파일이 있으면 오류(전체 덮어쓰기는 write_file 을 쓰도록).
    replace_all=True 면 search 가 여러 곳과 일치해도 전부 바꾼다.
    """
    if replace_all and search.strip() and file_exists and search in content:
        n = content.count(search)
        first = content.index(search)
        return EditApplication(
            new_content=content.replace(search, replace),
            method=MatchMethod.EXACT,
            start_line=content.count("\n", 0, first) + 1,
            replaced=n,
        )

    if search.strip() == "":
        if file_exists:
            raise EditError(
                "SEARCH 가 비어 있습니다. 기존 파일 전체를 바꾸려면 write_file 을 쓰세요."
            )
        return EditApplication(
            new_content=_ensure_trailing_nl(replace),
            method=MatchMethod.CREATE,
            start_line=0,
        )

    if not file_exists:
        raise EditError("파일이 존재하지 않습니다. 새 파일은 search 를 비워서 생성하세요.")

    # 1) 정확 일치 (유일)
    exact = _splice_exact(content, search, replace)
    if exact is not None:
        return exact

    # 2) 개행 정규화 후 정확 일치
    norm_content = content.replace("\r\n", "\n")
    norm_search = search.replace("\r\n", "\n")
    spliced = _splice_exact(norm_content, norm_search, replace.replace("\r\n", "\n"))
    if spliced is not None:
        return EditApplication(spliced.new_content, MatchMethod.NEWLINE, spliced.start_line)

    norm_replace = replace.replace("\r\n", "\n")

    # 3) 줄 단위 rstrip 비교
    line_match = _splice_by_lines(norm_content, norm_search, norm_replace, reindent=False)
    if line_match is not None:
        return line_match

    # 4) 들여쓰기 유연 매칭
    reindented = _splice_by_lines(norm_content, norm_search, norm_replace, reindent=True)
    if reindented is not None:
        return reindented

    raise EditError(
        "SEARCH 블록과 일치하는 부분을 찾지 못했습니다. "
        "파일을 다시 읽고 정확한 현재 내용으로 SEARCH 를 작성하세요.\n"
        f"찾으려던 내용(처음 5줄):\n{_head(search, 5)}"
    )


def _splice_exact(content: str, search: str, replace: str) -> EditApplication | None:
    count = content.count(search)
    if count == 0:
        return None
    if count > 1:
        raise EditError(
            f"SEARCH 블록이 {count}곳과 일치합니다. 앞뒤 줄을 더 포함해 유일하게 "
            "만들거나, 모두 바꾸려면 replace_all: true 를 넘기세요."
        )
    idx = content.index(search)
    new_content = content[:idx] + replace + content[idx + len(search) :]
    start_line = content.count("\n", 0, idx) + 1
    return EditApplication(new_content=new_content, method=MatchMethod.EXACT, start_line=start_line)


def _splice_by_lines(
    content: str, search: str, replace: str, *, reindent: bool
) -> EditApplication | None:
    c_lines = content.split("\n")
    s_lines = search.split("\n")
    if not s_lines:
        return None

    def norm(s: str) -> str:
        return s.strip() if reindent else s.rstrip()

    s_norm = [norm(x) for x in s_lines]
    matches: list[int] = []
    for start in range(len(c_lines) - len(s_lines) + 1):
        window = c_lines[start : start + len(s_lines)]
        if [norm(x) for x in window] == s_norm:
            matches.append(start)

    if len(matches) == 0:
        return None
    if len(matches) > 1:
        raise EditError(
            f"SEARCH 블록이 {len(matches)}곳과 (공백 무시) 일치합니다. 문맥을 더 포함하세요."
        )

    start = matches[0]
    r_lines = replace.split("\n")
    if reindent:
        first_orig = c_lines[start]
        indent = first_orig[: len(first_orig) - len(first_orig.lstrip())]
        first_search = s_lines[0]
        search_indent = first_search[: len(first_search) - len(first_search.lstrip())]
        r_lines = [_reindent(line, search_indent, indent) for line in r_lines]

    new_lines = c_lines[:start] + r_lines + c_lines[start + len(s_lines) :]
    method = MatchMethod.REINDENT if reindent else MatchMethod.RSTRIP
    return EditApplication(
        new_content="\n".join(new_lines), method=method, start_line=start + 1
    )


def _reindent(line: str, old_prefix: str, new_prefix: str) -> str:
    """replace 줄의 들여쓰기를 (old_prefix 기준 → new_prefix 기준) 으로 옮긴다."""
    if not line.strip():
        return line
    if old_prefix and line.startswith(old_prefix):
        return new_prefix + line[len(old_prefix) :]
    return new_prefix + line


def _ensure_trailing_nl(text: str) -> str:
    return text if text.endswith("\n") or text == "" else text + "\n"


def _head(text: str, n: int) -> str:
    return "\n".join(text.split("\n")[:n])
