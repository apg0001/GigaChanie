"""테스트 공용 fixture / 헬퍼."""

from __future__ import annotations

from collections.abc import Sequence

from gigachanie.serving.base import (
    ChatResponse,
    Message,
    StreamCallback,
    ToolCall,
    ToolSpec,
    Usage,
)


class ScriptedBackend:
    """미리 정해둔 응답을 순서대로 돌려주는 가짜 백엔드."""

    name = "scripted"
    model = "scripted-model"
    tool_mode = "native"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.received: list[list[Message]] = []
        self.closed = False

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stream_cb: StreamCallback | None = None,
        reasoning: str | None = None,
    ) -> ChatResponse:
        self.received.append(list(messages))
        self.last_reasoning = reasoning
        if not self._responses:
            return text_response("(대본 소진)")
        resp = self._responses.pop(0)
        if stream_cb and resp.message.content:
            stream_cb(resp.message.content)
        return resp

    async def health(self) -> tuple[bool, str]:
        return True, "ok"

    async def close(self) -> None:
        self.closed = True


def text_response(text: str, *, finish: str = "stop") -> ChatResponse:
    return ChatResponse(
        message=Message.assistant(text),
        finish_reason=finish,  # type: ignore[arg-type]
        usage=Usage(1, 1),
        model="scripted-model",
    )


def tool_response(name: str, arguments: dict[str, object], *, call_id: str = "c1") -> ChatResponse:
    call = ToolCall(id=call_id, name=name, arguments=arguments)
    return ChatResponse(
        message=Message.assistant("", [call]),
        finish_reason="tool_calls",
        usage=Usage(1, 1),
        model="scripted-model",
    )
