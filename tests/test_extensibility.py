"""커스텀 슬래시 명령 + 훅 테스트."""

import sys
from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.commands._slashfiles import load_custom_commands
from gigachanie.loop.agent import Agent
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.hooks import HookRunner
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import run_sync

PY = sys.executable


# ------------------------------------------------------------ 커스텀 명령


def test_load_custom_commands(tmp_path: Path) -> None:
    d = tmp_path / ".agent" / "commands"
    d.mkdir(parents=True)
    (d / "fixtest.md").write_text(
        "---\ndescription: 테스트 고치기\n---\n실패 테스트를 통과시켜라: $ARGUMENTS\n",
        encoding="utf-8",
    )
    (d / "explain.md").write_text("이 파일을 설명해줘 {{args}}", encoding="utf-8")

    cmds = load_custom_commands(tmp_path)
    assert set(cmds) == {"fixtest", "explain"}
    assert cmds["fixtest"].description == "테스트 고치기"
    assert cmds["fixtest"].expand("src/a.py") == "실패 테스트를 통과시켜라: src/a.py"
    assert cmds["explain"].expand("foo") == "이 파일을 설명해줘 foo"
    assert cmds["explain"].description.startswith("이 파일을 설명")


def test_없으면_빈딕셔너리(tmp_path: Path) -> None:
    assert load_custom_commands(tmp_path) == {}


# ------------------------------------------------------------ 훅


def _script(tmp_path: Path, name: str, code: str) -> str:
    p = tmp_path / name
    p.write_text(code, encoding="utf-8")
    return p.as_posix()


def _hooks(tmp_path: Path, spec: dict) -> HookRunner:
    import yaml

    d = tmp_path / ".agent"
    d.mkdir(exist_ok=True)
    (d / "hooks.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return HookRunner.load(tmp_path)


def test_hooks_없으면_비활성(tmp_path: Path) -> None:
    assert not HookRunner.load(tmp_path).enabled


def test_pre_tool_훅_차단(tmp_path: Path) -> None:
    guard = _script(tmp_path, "guard.py", "import sys; sys.exit(3)")
    hr = _hooks(
        tmp_path,
        {"pre_tool": [{"match": "write_file", "run": f'"{PY}" "{guard}"'}]},
    )
    assert hr.enabled
    reason = hr.check_pre_tool("write_file", {"path": "a"})
    assert reason is not None and "차단" in reason
    assert hr.check_pre_tool("read_file", {}) is None


def test_pre_tool_훅_통과(tmp_path: Path) -> None:
    ok = _script(tmp_path, "ok.py", "pass")
    hr = _hooks(tmp_path, {"pre_tool": [{"run": f'"{PY}" "{ok}"'}]})
    assert hr.check_pre_tool("write_file", {}) is None


def test_agent_루프에서_pre_tool_훅_차단(tmp_path: Path) -> None:
    guard = _script(tmp_path, "guard.py", "import sys; sys.exit(1)")
    hr = _hooks(tmp_path, {"pre_tool": [{"run": f'"{PY}" "{guard}"'}]})
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    backend = ScriptedBackend(
        [
            tool_response("read_file", {"path": "a.txt"}),
            text_response("훅에 막혔습니다."),
        ]
    )
    ctx = ToolContext(root=tmp_path, hooks=hr)
    agent = Agent(backend, build_registry(), ctx)
    result = run_sync(agent.run("읽어줘"))
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert tool_msgs and "차단" in tool_msgs[0].content


def test_session_start_stop_훅(tmp_path: Path) -> None:
    marker = (tmp_path / "fired.txt").as_posix()
    appender = _script(
        tmp_path,
        "append.py",
        f"import sys; open(r'{marker}', 'a').write(sys.argv[1])",
    )
    hr = _hooks(
        tmp_path,
        {
            "session_start": [{"run": f'"{PY}" "{appender}" s'}],
            "stop": [{"run": f'"{PY}" "{appender}" e'}],
        },
    )
    hr.fire("session_start")
    hr.fire("stop")
    assert Path(marker).read_text() == "se"
