"""승인 정책.

쓰기/실행 도구는 실행 전에 `ApprovalPolicy.check()` 를 통과해야 한다.
정책은 모드(suggest / auto-edit / full-auto)와 셸 허용·거부 목록,
그리고 대화형 승인 콜백(approver)으로 구성된다.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

ActionKind = Literal["write", "shell", "delete"]


class ApprovalMode(str, Enum):
    SUGGEST = "suggest"  # 모든 쓰기/실행에 확인
    AUTO_EDIT = "auto-edit"  # 파일 쓰기는 자동, 셸 실행은 확인
    FULL_AUTO = "full-auto"  # 전부 자동 (거부 목록만 차단)

    @classmethod
    def parse(cls, value: str) -> ApprovalMode:
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(
                f"알 수 없는 승인 모드: {value!r} "
                f"(suggest | auto-edit | full-auto)"
            ) from exc


@dataclass(frozen=True)
class ApprovalRequest:
    kind: ActionKind
    summary: str  # 한 줄 요약 (예: "파일 쓰기: src/foo.py")
    detail: str = ""  # diff 또는 명령 전문


# 대화형 승인 콜백: 요청을 받아 허용 여부를 반환
Approver = Callable[[ApprovalRequest], bool]

_DEFAULT_DENY_SHELL = [
    r"\brm\s+-rf\s+/",
    r":\(\)\s*\{",  # fork bomb
    r"\bmkfs\b",
    r"\bdd\s+if=.*of=/dev/",
    r">\s*/dev/sd",
    r"\bshutdown\b",
    r"\breboot\b",
]

_DEFAULT_ALLOW_SHELL = [
    r"^(ls|dir|pwd|cat|type|echo|head|tail|wc)\b",
    r"^git\s+(status|diff|log|show|branch|remote|rev-parse)\b",
    r"^(python|python3|py)\s+-m\s+pytest\b",
    r"^(pytest|ruff|mypy|black|flake8)\b",
    r"^npm\s+(test|run\s+lint|run\s+build)\b",
    r"^(node|deno)\s+--version\b",
]


@dataclass
class ApprovalPolicy:
    mode: ApprovalMode = ApprovalMode.SUGGEST
    approver: Approver | None = None
    allow_shell: list[str] = field(default_factory=lambda: list(_DEFAULT_ALLOW_SHELL))
    deny_shell: list[str] = field(default_factory=lambda: list(_DEFAULT_DENY_SHELL))

    def _shell_listed(self, cmd: str, patterns: list[str]) -> bool:
        return any(re.search(p, cmd.strip()) for p in patterns)

    def check(self, req: ApprovalRequest) -> tuple[bool, str]:
        """(허용 여부, 사유)."""
        if req.kind == "shell":
            if self._shell_listed(req.detail or req.summary, self.deny_shell):
                return False, "거부 목록에 해당하는 명령입니다."
            if self._shell_listed(req.detail or req.summary, self.allow_shell):
                return True, "허용 목록의 안전한 명령"
            if self.mode is ApprovalMode.FULL_AUTO:
                return True, "full-auto 모드"
            return self._ask(req)

        # write / delete
        if self.mode in (ApprovalMode.FULL_AUTO, ApprovalMode.AUTO_EDIT):
            return True, f"{self.mode.value} 모드"
        return self._ask(req)

    def _ask(self, req: ApprovalRequest) -> tuple[bool, str]:
        if self.approver is None:
            return (
                False,
                "승인 절차가 없어 거부되었습니다. 대화형으로 실행하거나 "
                "--auto / --yolo 옵션을 사용하세요.",
            )
        allowed = self.approver(req)
        return allowed, ("사용자 승인" if allowed else "사용자가 거부함")


def auto_policy() -> ApprovalPolicy:
    """비대화 환경 기본값: 읽기만 가능, 쓰기/실행은 거부."""
    return ApprovalPolicy(mode=ApprovalMode.SUGGEST, approver=None)
