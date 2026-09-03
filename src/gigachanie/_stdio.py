"""stdio JSON-RPC 서버 공용 헬퍼.

Windows 의 기본 콘솔/파이프 인코딩은 cp949 라서 한국어가 섞인 JSON 을
그대로 쓰면 상대가 UTF-8 로 못 읽는다. 서버 진입점에서 stdin/stdout 을
UTF-8·LF 로 고정한다.
"""

from __future__ import annotations

import contextlib
import sys
from typing import TextIO


def force_utf8_stdio() -> tuple[TextIO, TextIO]:
    """sys.stdin/stdout 을 UTF-8, 줄바꿈 LF 로 재설정하고 돌려준다."""
    for stream, translate in ((sys.stdin, None), (sys.stdout, "\n")):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", newline=translate)  # type: ignore[union-attr]
    return sys.stdin, sys.stdout
