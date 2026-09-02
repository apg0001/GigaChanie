"""사용자 입력의 `@경로` 참조를 확장한다.

- 텍스트 파일: 내용을 프롬프트 하단에 첨부
- 이미지(png/jpg/jpeg/gif/webp): base64 data URI 로 만들어 별도 반환 (멀티모달)
- PDF: pypdf 가 있으면 텍스트 추출, 없으면 안내

    "이 @src/foo.py 와 @design.png 를 봐줘"
"""

from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path

_REF_RE = re.compile(r"@(?:\"([^\"]+)\"|([^\s\"']+))")
_MAX_FILE_CHARS = 20_000
_MAX_TOTAL_CHARS = 60_000
_MAX_IMAGE_BYTES = 8_000_000
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@dataclass
class ExpandedRefs:
    text: str
    text_files: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)  # data URI
    image_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _pdf_text(path: Path) -> str | None:
    try:
        import pypdf
    except ModuleNotFoundError:
        return None
    try:
        reader = pypdf.PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages[:20])
    except Exception:
        # PDF 파싱 실패는 조용히 넘어간다 (손상·암호화 등).
        return None


def expand_file_refs(text: str, root: Path) -> tuple[str, list[str], list[str]]:
    """하위호환: (확장된 텍스트, 텍스트파일 목록, 이미지 data URI 목록)."""
    r = expand_refs(text, root)
    return r.text, r.text_files, r.images


def expand_refs(text: str, root: Path) -> ExpandedRefs:
    root = root.resolve()
    result = ExpandedRefs(text=text)
    seen: set[str] = set()
    attachments: list[str] = []
    total = 0

    for m in _REF_RE.finditer(text):
        rel = (m.group(1) or m.group(2)).rstrip(".,;:)")
        if rel in seen:
            continue
        seen.add(rel)

        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            result.notes.append(f"@{rel}: 작업 루트 밖 - 무시")
            continue
        if not target.is_file():
            continue

        ext = target.suffix.lower()
        if ext in _IMAGE_EXTS:
            data = target.read_bytes()
            if len(data) > _MAX_IMAGE_BYTES:
                result.notes.append(f"@{rel}: 이미지가 너무 큼 ({len(data)}B) - 무시")
                continue
            mime = mimetypes.guess_type(target.name)[0] or "image/png"
            uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
            result.images.append(uri)
            result.image_files.append(rel)
            continue

        if ext == ".pdf":
            pdf = _pdf_text(target)
            if pdf is None:
                result.notes.append(f"@{rel}: PDF 텍스트 추출 불가 (pip install pypdf)")
                continue
            body = pdf[:_MAX_FILE_CHARS]
        else:
            try:
                body = target.read_text("utf-8", errors="replace")[:_MAX_FILE_CHARS]
            except OSError as exc:
                result.notes.append(f"@{rel}: 읽기 실패 ({exc})")
                continue

        piece = f"# @{rel}\n```\n{body}\n```"
        if total + len(piece) > _MAX_TOTAL_CHARS:
            break
        attachments.append(piece)
        result.text_files.append(rel)
        total += len(piece)

    if attachments:
        result.text = text + "\n\n---\n참조된 파일:\n\n" + "\n\n".join(attachments)
    return result
