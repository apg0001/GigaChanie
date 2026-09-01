"""권한 설정 로드 + 경로 규칙 테스트."""

from pathlib import Path

from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.loop.approval import (
    ApprovalMode,
    ApprovalRequest,
    build_policy,
)
from gigachanie.permissions import DEFAULT_DENY_PATHS, load_permissions

runner = CliRunner()


def _write(tmp_path: Path, mode="", **lists) -> None:
    d = tmp_path / ".agent"
    d.mkdir(exist_ok=True)
    body = ""
    if mode:
        body += f"mode: {mode}\n"
    for k, v in lists.items():
        body += k + ":\n" + "".join(f"  - {x}\n" for x in v)
    (d / "permissions.yaml").write_text(body, encoding="utf-8")


def test_기본_보호경로_env_차단(tmp_path: Path) -> None:
    perms = load_permissions(tmp_path)
    pol = build_policy(ApprovalMode.FULL_AUTO, None, deny_paths=perms.effective_deny_paths())
    ok, reason = pol.check(ApprovalRequest(kind="write", summary="", path=".env"))
    assert not ok and "보호된 경로" in reason
    ok, _ = pol.check(ApprovalRequest(kind="write", summary="", path="src/config/app.py"))
    assert ok


def test_중첩_env_도_차단(tmp_path: Path) -> None:
    pol = build_policy(ApprovalMode.FULL_AUTO, None, deny_paths=list(DEFAULT_DENY_PATHS))
    for p in ("backend/.env", "a/b/id_rsa", "deep/.ssh/config", "x/secret.yaml"):
        ok, _ = pol.check(ApprovalRequest(kind="write", summary="", path=p))
        assert not ok, p


def test_프로젝트_설정_병합(tmp_path: Path) -> None:
    _write(
        tmp_path,
        mode="auto-edit",
        allow_paths=["src/**"],
        deny_paths=["config/prod/**"],
        deny_shell=["^git push"],
    )
    perms = load_permissions(tmp_path)
    assert perms.mode == "auto-edit"
    assert "src/**" in perms.allow_paths
    assert "config/prod/**" in perms.effective_deny_paths()
    assert ".env" in perms.effective_deny_paths()  # 기본값도 포함


def test_allow_paths_는_모드무관_자동승인(tmp_path: Path) -> None:
    _write(tmp_path, allow_paths=["src/**"])
    perms = load_permissions(tmp_path)
    pol = build_policy(
        ApprovalMode.SUGGEST, None,  # approver 없음 → 원래는 거부
        allow_paths=perms.allow_paths,
        deny_paths=perms.effective_deny_paths(),
    )
    ok, reason = pol.check(ApprovalRequest(kind="write", summary="", path="src/x.py"))
    assert ok and "허용 경로" in reason
    # allow 목록 밖은 여전히 거부
    ok, _ = pol.check(ApprovalRequest(kind="write", summary="", path="docs/x.md"))
    assert not ok


def test_deny_가_allow_보다_우선(tmp_path: Path) -> None:
    pol = build_policy(
        ApprovalMode.FULL_AUTO, None,
        allow_paths=["**/*"],
        deny_paths=[".env"],
    )
    ok, _ = pol.check(ApprovalRequest(kind="write", summary="", path=".env"))
    assert not ok


def test_사용자_deny_shell_병합(tmp_path: Path) -> None:
    _write(tmp_path, deny_shell=["^curl "])
    perms = load_permissions(tmp_path)
    pol = build_policy(
        ApprovalMode.FULL_AUTO, None, extra_deny_shell=perms.deny_shell
    )
    ok, _ = pol.check(ApprovalRequest(kind="shell", summary="", detail="curl http://x"))
    assert not ok
    # 기본 거부 목록도 여전히 유효
    ok, _ = pol.check(ApprovalRequest(kind="shell", summary="", detail="rm -rf /"))
    assert not ok


def test_giga_policy_cli(tmp_path: Path) -> None:
    _write(tmp_path, mode="auto-edit", allow_paths=["lib/**"])
    result = runner.invoke(app, ["policy", "-C", str(tmp_path)])
    assert result.exit_code == 0
    assert "auto-edit" in result.stdout
    assert "lib/**" in result.stdout
    assert ".env" in result.stdout
