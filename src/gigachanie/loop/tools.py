"""도구 추상화.

Tool 은 이름/설명/JSON 스키마(ToolSpec)와 실행 함수를 가진다.
ToolRegistry 가 이를 모아 백엔드에 넘길 스펙 목록과 이름→도구 매핑을 제공한다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from gigachanie.loop.approval import ApprovalPolicy
from gigachanie.loop.checkpoint import CheckpointStore
from gigachanie.serving.base import ToolSpec


@dataclass
class ToolContext:
    """도구 실행 환경."""

    root: Path
    # 쓰기/실행 도구가 참조하는 승인 정책. 기본값은 "쓰기/실행 거부".
    policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)
    # 편집 스냅샷 저장소. None 이면 체크포인트 비활성.
    checkpoints: CheckpointStore | None = None
    # 도구가 남기는 부가 메모(감사 로그 등)
    scratch: dict[str, Any] = field(default_factory=dict)

    def snapshot(self, path: Path) -> None:
        if self.checkpoints is not None:
            self.checkpoints.before_write(path)

    def resolve(self, rel: str) -> Path:
        """루트 기준 상대경로를 절대경로로. 루트 밖으로 벗어나면 예외."""
        p = (self.root / rel).resolve()
        root = self.root.resolve()
        if p != root and root not in p.parents:
            raise ToolError(f"작업 루트 밖의 경로에 접근할 수 없습니다: {rel}")
        return p


@dataclass
class ToolResult:
    content: str
    is_error: bool = False

    @classmethod
    def error(cls, msg: str) -> ToolResult:
        return cls(content=msg, is_error=True)


class ToolError(Exception):
    """도구 실행 중 사용자에게 돌려줄 오류 (루프를 죽이지 않고 모델에 피드백)."""


ToolFunc = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@runtime_checkable
class Tool(Protocol):
    spec: ToolSpec

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


@dataclass
class FunctionTool:
    """함수 하나를 Tool 로 감싸는 간단한 구현."""

    spec: ToolSpec
    func: ToolFunc

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return await self.func(args, ctx)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.spec.name] = tool

    def register_func(
        self, name: str, description: str, parameters: dict[str, Any], func: ToolFunc
    ) -> None:
        self.register(FunctionTool(ToolSpec(name, description, parameters), func))

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def __len__(self) -> int:
        return len(self._tools)
