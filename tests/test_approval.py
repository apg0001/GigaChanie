"""승인 정책 테스트."""

import pytest

from gigachanie.loop.approval import (
    ApprovalMode,
    ApprovalPolicy,
    ApprovalRequest,
)

WRITE = ApprovalRequest(kind="write", summary="쓰기: a.py", detail="--- a\n+++ b\n")
SHELL_SAFE = ApprovalRequest(kind="shell", summary="셸: git status", detail="git status")
SHELL_UNKNOWN = ApprovalRequest(kind="shell", summary="셸: curl x", detail="curl http://x")
SHELL_DANGER = ApprovalRequest(kind="shell", summary="셸", detail="rm -rf /")


def test_모드_파싱() -> None:
    assert ApprovalMode.parse("auto-edit") is ApprovalMode.AUTO_EDIT
    with pytest.raises(ValueError):
        ApprovalMode.parse("nope")


def test_suggest_모드_쓰기는_승인필요() -> None:
    denied = ApprovalPolicy(mode=ApprovalMode.SUGGEST, approver=None)
    ok, _ = denied.check(WRITE)
    assert ok is False

    granted = ApprovalPolicy(mode=ApprovalMode.SUGGEST, approver=lambda _r: True)
    ok, _ = granted.check(WRITE)
    assert ok is True


def test_auto_edit_모드_쓰기는_자동_셸은_확인() -> None:
    calls: list[ApprovalRequest] = []
    pol = ApprovalPolicy(mode=ApprovalMode.AUTO_EDIT, approver=lambda r: calls.append(r) or True)
    assert pol.check(WRITE)[0] is True
    assert not calls  # 쓰기는 approver 호출 안 함
    assert pol.check(SHELL_UNKNOWN)[0] is True
    assert calls  # 셸은 approver 호출


def test_full_auto_는_거부목록만_차단() -> None:
    pol = ApprovalPolicy(mode=ApprovalMode.FULL_AUTO, approver=None)
    assert pol.check(WRITE)[0] is True
    assert pol.check(SHELL_UNKNOWN)[0] is True
    assert pol.check(SHELL_DANGER)[0] is False


def test_허용목록_명령은_모드무관_자동승인() -> None:
    pol = ApprovalPolicy(mode=ApprovalMode.SUGGEST, approver=None)
    assert pol.check(SHELL_SAFE)[0] is True


def test_거부목록_명령은_모드무관_차단() -> None:
    pol = ApprovalPolicy(mode=ApprovalMode.FULL_AUTO, approver=lambda _r: True)
    ok, reason = pol.check(SHELL_DANGER)
    assert ok is False
    assert "거부 목록" in reason
