"""백엔드 공통 타입과 프로토콜."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]

# 스트리밍 델타 콜백. 반환값은 무시한다.
StreamCallback = Callable[[str], None]


@dataclass
class ToolCall:
    """모델이 요청한 도구 호출."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """대화 메시지 하나."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # role == "tool" 일 때: 어떤 호출에 대한 결과인지
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: list[ToolCall] | None = None) -> Message:
        return cls(role="assistant", content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool_result(cls, call: ToolCall, content: str) -> Message:
        return cls(role="tool", content=content, tool_call_id=call.id, name=call.name)


@dataclass(frozen=True)
class ToolSpec:
    """도구 정의 (JSON Schema 파라미터)."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


FinishReason = Literal["stop", "tool_calls", "length", "error"]


@dataclass
class ChatResponse:
    message: Message
    finish_reason: FinishReason
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: dict[str, Any] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.message.tool_calls)


class BackendError(RuntimeError):
    """백엔드 호출 실패 (연결 불가, HTTP 오류, 응답 파싱 실패 등)."""


@runtime_checkable
class Backend(Protocol):
    """에이전트 루프가 의존하는 유일한 인터페이스.

    model / tool_mode 는 읽기 전용으로 취급한다 (일반 속성 또는 property 모두 허용).
    """

    name: str

    @property
    def model(self) -> str: ...

    @property
    def tool_mode(self) -> Literal["native", "prompt", "none"]: ...

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stream_cb: StreamCallback | None = None,
    ) -> ChatResponse: ...

    async def health(self) -> tuple[bool, str]:
        """(정상 여부, 메시지). 연결/모델 로드 확인용."""
        ...

    async def close(self) -> None: ...


def run_sync(coro: Awaitable[Any]) -> Any:
    """동기 컨텍스트(CLI 등)에서 코루틴을 실행하는 헬퍼."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    raise RuntimeError("run_sync 는 이미 실행 중인 이벤트 루프 안에서 호출할 수 없습니다.")
