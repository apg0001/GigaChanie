"""서브에이전트 도구.

`run_subagent` 로 하위 작업을 **독립 컨텍스트**의 에이전트에 위임한다.
부모의 대화 히스토리를 물려받지 않으므로, 조사·요약처럼 맥락이 많이 쌓이는
작업을 떼어내 부모 컨텍스트를 아끼는 데 쓴다.

무한 재귀를 막기 위해 깊이를 제한한다(기본 2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.tools import ToolContext, ToolError, ToolRegistry, ToolResult
from gigachanie.serving.base import Backend

_MAX_DEPTH = 2


def register_subagent_tool(
    reg: ToolRegistry,
    *,
    backend: Backend,
    root: Path,
    parent_ctx: ToolContext,
    parent_writable: bool,
    depth: int = 0,
    max_steps: int = 12,
) -> None:
    """레지스트리에 run_subagent 를 등록한다. depth 가 한계면 등록하지 않는다."""
    if depth >= _MAX_DEPTH:
        return

    async def _run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from gigachanie.loop.agent import Agent

        task = args.get("task")
        if not task or not isinstance(task, str):
            raise ToolError("task 인자(문자열)가 필요합니다.")
        want_write = bool(args.get("write", False)) and parent_writable

        sub_reg = build_registry(writable=want_write)
        register_subagent_tool(
            sub_reg,
            backend=backend,
            root=root,
            parent_ctx=parent_ctx,
            parent_writable=parent_writable,
            depth=depth + 1,
            max_steps=max_steps,
        )
        sub_ctx = ToolContext(
            root=root,
            policy=parent_ctx.policy,
            checkpoints=parent_ctx.checkpoints if want_write else None,
            procman=parent_ctx.procman if want_write else None,
            hooks=parent_ctx.hooks,
            sandbox=parent_ctx.sandbox,
            allow_network=parent_ctx.allow_network,
        )
        agent = Agent(backend, sub_reg, sub_ctx, max_steps=max_steps)
        result = await agent.run(task)
        head = "완료" if result.ok else f"중단({result.stop_reason})"
        return ToolResult(
            content=(
                f"[서브에이전트 {head} · 스텝 {result.steps} · "
                f"토큰 {result.usage.total_tokens}]\n{result.final_text}"
            ),
            is_error=not result.ok,
        )

    scope = "읽기·검색만" if not parent_writable else "읽기/쓰기(write:true 시)"
    reg.register_func(
        "run_subagent",
        f"하위 작업을 독립 컨텍스트의 에이전트에 맡긴다({scope}). 부모 대화는 "
        "물려받지 않으므로 task 에 필요한 배경을 스스로 담아야 한다. 조사·요약처럼 "
        "중간 산출물이 많은 작업에 쓴다. 결과는 최종 답변 텍스트로 돌아온다.",
        {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "서브에이전트에게 시킬 작업 (자기완결적으로 기술)",
                },
                "write": {
                    "type": "boolean",
                    "description": "파일 수정 허용 (부모가 쓰기 모드일 때만 유효). 기본 false",
                },
            },
            "required": ["task"],
        },
        _run,
    )
