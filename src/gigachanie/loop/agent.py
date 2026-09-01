"""에이전트 툴 루프.

한 번의 사용자 입력에 대해: 모델 호출 → 도구 실행 → 결과 주입 을
최종 답변이 나오거나 스텝 예산을 초과할 때까지 반복한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from gigachanie.loop.prompt import build_system_prompt
from gigachanie.loop.tools import ToolContext, ToolError, ToolRegistry, ToolResult
from gigachanie.serving.base import Backend, BackendError, Message, ToolCall, Usage

EventKind = Literal[
    "step",
    "assistant_delta",
    "assistant_text",
    "tool_call",
    "tool_result",
    "done",
    "error",
]


@dataclass
class AgentEvent:
    kind: EventKind
    text: str = ""
    tool_name: str = ""
    tool_args: dict[str, object] = field(default_factory=dict)
    is_error: bool = False
    step: int = 0


EventHandler = Callable[[AgentEvent], None]

StopReason = Literal["done", "max_steps", "error"]


@dataclass
class AgentResult:
    final_text: str
    stop_reason: StopReason
    steps: int
    messages: list[Message]
    usage: Usage

    @property
    def ok(self) -> bool:
        return self.stop_reason == "done"


def _args_signature(call: ToolCall) -> str:
    try:
        return f"{call.name}:{json.dumps(call.arguments, sort_keys=True, ensure_ascii=False)}"
    except (TypeError, ValueError):
        return f"{call.name}:{call.arguments!r}"


class Agent:
    def __init__(
        self,
        backend: Backend,
        tools: ToolRegistry,
        ctx: ToolContext,
        *,
        system_prompt: str | None = None,
        project_context: str | None = None,
        repo_map: str | None = None,
        max_steps: int = 20,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        history: Sequence[Message] | None = None,
        repeat_limit: int = 3,
    ) -> None:
        self.backend = backend
        self.tools = tools
        self.ctx = ctx
        self.system_prompt = system_prompt or build_system_prompt(
            project_context=project_context, repo_map=repo_map
        )
        self.max_steps = max_steps
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.repeat_limit = repeat_limit
        self.messages: list[Message] = [Message.system(self.system_prompt)]
        if history:
            self.messages.extend(history)
        self._usage = Usage()
        self._call_counts: dict[str, int] = {}

    # ------------------------------------------------------------------ run

    async def run(
        self, user_input: str, *, on_event: EventHandler | None = None
    ) -> AgentResult:
        emit = on_event or (lambda _e: None)
        self.messages.append(Message.user(user_input))

        stop: StopReason = "max_steps"
        final_text = ""

        for step in range(1, self.max_steps + 1):
            emit(AgentEvent(kind="step", step=step))

            stream_target: list[str] = []

            def _delta(
                chunk: str,
                _sink: list[str] = stream_target,
                _step: int = step,
            ) -> None:
                _sink.append(chunk)
                emit(AgentEvent(kind="assistant_delta", text=chunk, step=_step))

            try:
                resp = await self.backend.chat(
                    self.messages,
                    tools=self.tools.specs() or None,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    stream_cb=_delta,
                )
            except BackendError as exc:
                emit(AgentEvent(kind="error", text=str(exc), is_error=True, step=step))
                return AgentResult(
                    final_text=str(exc),
                    stop_reason="error",
                    steps=step,
                    messages=self.messages,
                    usage=self._usage,
                )

            self._usage = Usage(
                self._usage.prompt_tokens + resp.usage.prompt_tokens,
                self._usage.completion_tokens + resp.usage.completion_tokens,
            )
            self.messages.append(resp.message)

            if resp.message.content:
                emit(
                    AgentEvent(
                        kind="assistant_text", text=resp.message.content, step=step
                    )
                )

            if not resp.has_tool_calls:
                final_text = resp.message.content
                stop = "done"
                break

            guard_hit = await self._run_tool_calls(resp.message.tool_calls, step, emit)
            if guard_hit:
                final_text = (
                    "같은 도구 호출이 반복되어 중단했습니다. "
                    "다른 접근이 필요합니다."
                )
                self.messages.append(Message.user(final_text))
                stop = "max_steps"
                break
        else:
            final_text = (
                f"최대 스텝({self.max_steps})에 도달했습니다. 작업이 완료되지 않았을 수 있습니다."
            )

        emit(AgentEvent(kind="done", text=final_text))
        return AgentResult(
            final_text=final_text,
            stop_reason=stop,
            steps=min(step, self.max_steps),
            messages=self.messages,
            usage=self._usage,
        )

    # ------------------------------------------------------------- tool calls

    async def _run_tool_calls(
        self, calls: list[ToolCall], step: int, emit: EventHandler
    ) -> bool:
        """도구들을 실행해 결과 메시지를 추가한다. 반복 가드에 걸리면 True."""
        for call in calls:
            sig = _args_signature(call)
            self._call_counts[sig] = self._call_counts.get(sig, 0) + 1
            emit(
                AgentEvent(
                    kind="tool_call",
                    tool_name=call.name,
                    tool_args=call.arguments,
                    step=step,
                )
            )

            if self._call_counts[sig] > self.repeat_limit:
                return True

            result = await self._invoke(call)
            emit(
                AgentEvent(
                    kind="tool_result",
                    tool_name=call.name,
                    text=result.content,
                    is_error=result.is_error,
                    step=step,
                )
            )
            self.messages.append(Message.tool_result(call, result.content))
        return False

    async def _invoke(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult.error(
                f"알 수 없는 도구 '{call.name}'. 사용 가능: {', '.join(self.tools.names())}"
            )
        try:
            return await tool.run(call.arguments, self.ctx)
        except ToolError as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:
            # 도구 내부 오류는 루프를 죽이지 않고 모델에 피드백한다.
            return ToolResult.error(f"{type(exc).__name__}: {exc}")
