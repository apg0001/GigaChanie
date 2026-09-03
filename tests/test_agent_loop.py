"""에이전트 툴 루프 테스트."""

from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.loop.agent import Agent, AgentEvent
from gigachanie.loop.builtin_tools import build_registry, default_readonly_registry
from gigachanie.loop.tools import ToolContext, ToolRegistry, ToolResult
from gigachanie.serving.base import run_sync


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(root=tmp_path)


def test_도구호출_후_최종답변(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    backend = ScriptedBackend(
        [
            tool_response("read_file", {"path": "a.txt"}),
            text_response("파일 내용은 hello 입니다."),
        ]
    )
    agent = Agent(backend, default_readonly_registry(), _ctx(tmp_path))
    events: list[AgentEvent] = []
    result = run_sync(agent.run("a.txt 읽어줘", on_event=events.append))

    assert result.ok
    assert result.stop_reason == "done"
    assert "hello" in result.final_text
    kinds = [e.kind for e in events]
    assert "tool_call" in kinds and "tool_result" in kinds
    # tool 결과 메시지가 대화에 들어갔는지
    assert any(m.role == "tool" for m in result.messages)


def test_알수없는_도구는_오류로_피드백(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [
            tool_response("does_not_exist", {}),
            text_response("도구가 없어 다른 방법을 씁니다."),
        ]
    )
    agent = Agent(backend, default_readonly_registry(), _ctx(tmp_path))
    result = run_sync(agent.run("뭔가 해줘"))
    assert result.ok
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert tool_msgs and "알 수 없는 도구" in tool_msgs[0].content


def test_토큰_예산_초과시_중단(tmp_path: Path) -> None:
    from gigachanie.serving.base import Usage

    def big(text: str):
        r = text_response(text)
        r.usage = Usage(prompt_tokens=50, completion_tokens=10)
        return r

    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    backend = ScriptedBackend(
        [tool_response("read_file", {"path": "a.txt"}) for _ in range(5)]
    )
    for r in backend._responses:
        r.usage = Usage(prompt_tokens=50, completion_tokens=10)
    agent = Agent(
        backend, default_readonly_registry(), _ctx(tmp_path), token_budget=80
    )
    result = run_sync(agent.run("반복"))
    assert result.stop_reason == "budget"


def test_ctrl_c_는_깔끔하게_중단(tmp_path: Path) -> None:
    class Boom(ScriptedBackend):
        async def chat(self, *a, **k):  # type: ignore[override]
            raise KeyboardInterrupt

    agent = Agent(Boom([]), default_readonly_registry(), _ctx(tmp_path))
    result = run_sync(agent.run("작업"))
    assert result.stop_reason == "cancelled"
    assert "중단" in result.final_text


def test_도구없이_설명만하면_한번_더_시킨다(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    backend = ScriptedBackend(
        [
            text_response("네, a.txt 를 수정하겠습니다."),  # 의도만, 도구 없음 → 넛지
            tool_response("write_file", {"path": "a.txt", "content": "new"}),
            text_response("완료했습니다."),
        ]
    )
    from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy

    ctx = ToolContext(
        root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO)
    )
    agent = Agent(backend, build_registry(writable=True), ctx)
    result = run_sync(agent.run("a.txt 를 new 로 바꿔"))
    assert result.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new"


def test_넛지_상한_후_종료(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [text_response("코드를 작성하겠습니다.\n```python\nx=1\n```") for _ in range(8)]
    )
    from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy

    ctx = ToolContext(
        root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO)
    )
    agent = Agent(backend, build_registry(writable=True), ctx, max_steps=15)
    result = run_sync(agent.run("작업"))
    # 넛지 상한 후엔 그냥 done 으로 끝난다 (무한 루프 아님)
    assert result.stop_reason == "done"
    assert result.steps <= 5


def test_읽기전용이면_넛지_안함(tmp_path: Path) -> None:
    from gigachanie.loop.builtin_tools import default_readonly_registry

    backend = ScriptedBackend([text_response("설명하겠습니다.\n```py\nx\n```")])
    agent = Agent(backend, default_readonly_registry(), _ctx(tmp_path))
    result = run_sync(agent.run("설명해"))
    assert result.stop_reason == "done" and result.steps == 1


def test_반복_가드(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    # 같은 도구 호출을 계속 반환
    backend = ScriptedBackend([tool_response("read_file", {"path": "a.txt"}) for _ in range(10)])
    agent = Agent(backend, default_readonly_registry(), _ctx(tmp_path), repeat_limit=3)
    result = run_sync(agent.run("반복"))
    assert result.stop_reason == "max_steps"
    assert "반복" in result.final_text


def test_반복가드_후_메시지_짝_유지(tmp_path: Path) -> None:
    """반복 가드로 중단해도 tool_calls 는 전부 tool 결과로 답해 둬야 한다.

    안 그러면 세션 복원·chat 재개 시 백엔드가 메시지 짝이 안 맞는다고 거부한다.
    """
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    backend = ScriptedBackend(
        [tool_response("read_file", {"path": "a.txt"}) for _ in range(10)]
    )
    agent = Agent(backend, default_readonly_registry(), _ctx(tmp_path), repeat_limit=3)
    result = run_sync(agent.run("반복"))

    for i, msg in enumerate(result.messages):
        if msg.role == "assistant" and msg.tool_calls:
            answered = {
                m.tool_call_id
                for m in result.messages[i + 1 :]
                if m.role == "tool"
            }
            for call in msg.tool_calls:
                assert call.id in answered, f"메시지[{i}] tool_call {call.id} 미응답"


def test_최대_스텝_도달(tmp_path: Path) -> None:
    reg = ToolRegistry()

    calls = {"n": 0}

    async def _counter(args: dict[str, object], ctx: ToolContext) -> ToolResult:
        calls["n"] += 1
        return ToolResult(content=f"호출 {calls['n']}")

    reg.register_func("noop", "아무것도 안 함", {"type": "object", "properties": {}}, _counter)

    # 매번 다른 인자로 도구 호출 → 반복가드 회피, 스텝 소진
    backend = ScriptedBackend(
        [tool_response("noop", {"i": i}, call_id=f"c{i}") for i in range(50)]
    )
    agent = Agent(backend, reg, _ctx(tmp_path), max_steps=5)
    result = run_sync(agent.run("계속"))
    assert result.stop_reason == "max_steps"
    assert result.steps == 5


def test_백엔드_오류_처리(tmp_path: Path) -> None:
    from gigachanie.serving.base import BackendError

    class Boom(ScriptedBackend):
        async def chat(self, *a, **k):  # type: ignore[override]
            raise BackendError("연결 끊김")

    agent = Agent(Boom([]), default_readonly_registry(), _ctx(tmp_path))
    result = run_sync(agent.run("hi"))
    assert result.stop_reason == "error"
    assert "연결 끊김" in result.final_text


def test_지어낸_tool_response_는_넛지(tmp_path: Path) -> None:
    from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy

    backend = ScriptedBackend(
        [
            text_response("<tool_response>\n파일 내용: x=1\n</tool_response>"),
            tool_response("write_file", {"path": "a.txt", "content": "real"}),
            text_response("완료"),
        ]
    )
    ctx = ToolContext(root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO))
    agent = Agent(backend, build_registry(writable=True), ctx)
    result = run_sync(agent.run("a.txt 만들어"))
    assert result.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "real"
    # 넛지 메시지가 환각용이었는지
    assert any("지어낸" in m.content for m in result.messages if m.role == "user")
