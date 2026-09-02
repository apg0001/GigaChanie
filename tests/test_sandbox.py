"""셸 샌드박스 테스트."""

import sys
from pathlib import Path

from gigachanie.loop.sandbox import SandboxPlan, detect_sandbox


def test_detect_sandbox_안깨짐() -> None:
    plan = detect_sandbox()
    assert isinstance(plan, SandboxPlan)
    assert plan.note  # 항상 설명이 있음
    if sys.platform.startswith("win"):
        assert not plan.available


def test_wrap_비활성이면_그대로(tmp_path: Path) -> None:
    plan = SandboxPlan(available=False)
    argv = ["/bin/sh", "-c", "echo hi"]
    assert plan.wrap(argv, root=tmp_path, allow_net=True) == argv


def test_wrap_bwrap(tmp_path: Path) -> None:
    plan = SandboxPlan(available=True, tool="bwrap")
    wrapped = plan.wrap(["/bin/sh", "-c", "x"], root=tmp_path, allow_net=False)
    assert wrapped[0] == "bwrap"
    assert "--unshare-net" in wrapped
    assert str(tmp_path) in wrapped
    assert wrapped[-3:] == ["/bin/sh", "-c", "x"]

    with_net = plan.wrap(["/bin/sh"], root=tmp_path, allow_net=True)
    assert "--unshare-net" not in with_net


def test_wrap_firejail(tmp_path: Path) -> None:
    plan = SandboxPlan(available=True, tool="firejail")
    w = plan.wrap(["ls"], root=tmp_path, allow_net=False)
    assert w[0] == "firejail" and "--net=none" in w


def test_wrap_sandbox_exec_프로파일_생성(tmp_path: Path) -> None:
    plan = SandboxPlan(available=True, tool="sandbox-exec")
    w = plan.wrap(["echo", "x"], root=tmp_path, allow_net=False)
    assert w[0] == "sandbox-exec" and w[1] == "-f"
    profile = Path(w[2])
    assert profile.is_file()
    text = profile.read_text("utf-8")
    assert str(tmp_path) in text and "(deny network*)" in text


def test_run_shell_샌드박스_주입(tmp_path: Path, monkeypatch) -> None:
    from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
    from gigachanie.loop.builtin_tools import build_registry
    from gigachanie.loop.tools import ToolContext
    from gigachanie.serving.base import run_sync

    captured: dict = {}

    async def fake_exec(*argv, **kw):
        captured["argv"] = list(argv)

        class P:
            returncode = 0

            async def communicate(self):
                return (b"ok", b"")

        return P()

    import gigachanie.loop.write_tools as wt

    monkeypatch.setattr(wt.asyncio, "create_subprocess_exec", fake_exec)

    plan = SandboxPlan(available=True, tool="firejail")
    ctx = ToolContext(
        root=tmp_path,
        policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO),
        sandbox=plan,
        allow_network=False,
    )
    tool = build_registry(writable=True).get("run_shell")
    res = run_sync(tool.run({"command": "echo hi"}, ctx))
    assert not res.is_error
    assert captured["argv"][0] == "firejail"
    assert "[firejail]" in res.content
