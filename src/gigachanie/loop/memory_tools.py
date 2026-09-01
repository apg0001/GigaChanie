"""메모리 도구: read_memory (읽기), save_memory (쓰기)."""

from __future__ import annotations

from typing import Any

from gigachanie.context.memory import MemoryStore
from gigachanie.loop.approval import ApprovalRequest
from gigachanie.loop.tools import ToolContext, ToolError, ToolRegistry, ToolResult


async def _read_memory(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    store = MemoryStore(ctx.root)
    slug = args.get("slug")
    query = args.get("query")

    if slug:
        entry = store.get(str(slug))
        if entry is None:
            available = ", ".join(e.slug for e in store.all_entries()) or "(없음)"
            return ToolResult.error(f"메모리 '{slug}' 없음. 사용 가능: {available}")
        return ToolResult(content=f"# {entry.title}\n{entry.body}")

    if query:
        hits = store.search(str(query), limit=3)
        if not hits:
            return ToolResult(content=f"'{query}' 와 관련된 메모리 없음")
        parts = [f"## {e.slug} — {e.title}\n{e.body}" for e in hits]
        return ToolResult(content="\n\n".join(parts))

    raise ToolError("slug 또는 query 인자가 필요합니다.")


async def _save_memory(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    title = args.get("title")
    body = args.get("body")
    if not title or not body:
        raise ToolError("title 과 body 인자가 필요합니다.")
    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    allowed, reason = ctx.policy.check(
        ApprovalRequest(
            kind="write",
            summary=f"메모리 저장: {title}",
            detail=f"{title}\n\n{body}",
        )
    )
    if not allowed:
        return ToolResult.error(f"메모리 저장 거부됨 ({reason})")

    entry = MemoryStore(ctx.root).add(str(title), str(body), list(tags))
    return ToolResult(content=f"메모리 저장됨: {entry.slug} ({entry.path})")


def register_read_memory(reg: ToolRegistry) -> None:
    reg.register_func(
        "read_memory",
        "장기 메모리 본문을 읽는다. slug 로 특정 항목을, query 로 관련 항목을 찾는다.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "메모리 식별자"},
                "query": {"type": "string", "description": "검색어"},
            },
        },
        _read_memory,
    )


def register_save_memory(reg: ToolRegistry) -> None:
    reg.register_func(
        "save_memory",
        "이후 세션에서도 쓸 정보를 장기 메모리에 저장한다. 프로젝트 규칙·결정·맥락 등.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "body"],
        },
        _save_memory,
    )
