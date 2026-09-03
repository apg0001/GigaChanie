"""Ollama 전용 백엔드.

`/api/chat` 를 사용해 num_ctx · keep_alive 등 Ollama 고유 옵션을 제어한다.
(OpenAI 호환 /v1 경로로도 접근 가능하지만 컨텍스트 길이 지정이 안 되므로 전용 구현을 둔다.)
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Sequence
from typing import Any, Literal

import httpx

from gigachanie.serving.base import (
    BackendError,
    ChatResponse,
    FinishReason,
    Message,
    StreamCallback,
    ToolCall,
    ToolSpec,
    Usage,
)
from gigachanie.serving.toolcall import (
    StreamGate,
    normalize_native,
    parse_prompt_toolcalls,
    render_prompt_tool_docs,
)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)
_DEFAULT_HOST = "http://127.0.0.1:11434"


def _strip_data_uri(uri: str) -> str:
    if uri.startswith("data:") and ";base64," in uri:
        return uri.split(";base64,", 1)[1]
    return uri


def _message_to_wire(msg: Message) -> dict[str, Any]:
    if msg.role == "tool":
        return {"role": "tool", "content": msg.content}
    out: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.images:
        out["images"] = [_strip_data_uri(u) for u in msg.images]
    if msg.tool_calls:
        out["tool_calls"] = [
            {"function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in msg.tool_calls
        ]
    return out


class OllamaBackend:
    """Ollama /api/chat 백엔드."""

    def __init__(
        self,
        model: str,
        *,
        host: str | None = None,
        tool_mode: Literal["native", "prompt", "none"] = "native",
        num_ctx: int | None = None,
        keep_alive: str = "10m",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.name = "ollama"
        self.tool_mode = tool_mode
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.host = (host or os.environ.get("OLLAMA_HOST") or _DEFAULT_HOST).rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"http://{self.host}"
        self._client = client or httpx.AsyncClient(
            base_url=self.host, timeout=_DEFAULT_TIMEOUT
        )
        self._owns_client = client is None

    def _build_payload(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
        reasoning: str | None = None,
    ) -> dict[str, Any]:
        wire = [_message_to_wire(m) for m in messages]

        if tools and self.tool_mode == "prompt":
            docs = render_prompt_tool_docs(list(tools))
            if wire and wire[0]["role"] == "system":
                wire[0]["content"] += "\n\n" + docs
            else:
                wire.insert(0, {"role": "system", "content": docs})

        options: dict[str, Any] = {"temperature": temperature}
        if self.num_ctx:
            options["num_ctx"] = self.num_ctx
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": wire,
            "stream": stream,
            "keep_alive": self.keep_alive,
            "options": options,
        }
        if reasoning:
            # Ollama /api/chat 의 think: bool (gpt-oss 계열은 "low"/"medium"/"high")
            payload["think"] = reasoning if reasoning in ("low", "medium", "high") else True
        if tools and self.tool_mode == "native":
            payload["tools"] = [t.to_openai() for t in tools]
        return payload

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
        stream = stream_cb is not None
        payload = self._build_payload(
            messages, tools, temperature, max_tokens, stream, reasoning
        )
        try:
            if stream:
                return await self._chat_streaming(payload, stream_cb, tools)
            return await self._chat_once(payload, tools)
        except httpx.HTTPError as exc:
            raise BackendError(f"ollama 요청 실패: {exc}") from exc

    async def _chat_once(
        self, payload: dict[str, Any], tools: Sequence[ToolSpec] | None
    ) -> ChatResponse:
        resp = await self._client.post("/api/chat", json=payload)
        if resp.status_code >= 400:
            raise BackendError(f"ollama HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        return self._parse(data, tools)

    async def _chat_streaming(
        self,
        payload: dict[str, Any],
        stream_cb: StreamCallback | None,
        tools: Sequence[ToolSpec] | None,
    ) -> ChatResponse:
        parts: list[str] = []
        raw_calls: list[dict[str, Any]] = []
        last: dict[str, Any] = {}
        gate = StreamGate(stream_cb or (lambda _s: None), active=bool(tools))
        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")
                raise BackendError(f"ollama HTTP {resp.status_code}: {body[:500]}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                last = obj
                msg = obj.get("message", {})
                if msg.get("content"):
                    parts.append(msg["content"])
                    gate.feed(msg["content"])
                for tc in msg.get("tool_calls", []) or []:
                    raw_calls.append(tc)
                if obj.get("done"):
                    break

        content = "".join(parts)
        calls = normalize_native(raw_calls)
        cleaned = content
        if not calls and tools:
            known = {t.name for t in tools}
            calls, cleaned = parse_prompt_toolcalls(content, known)
        gate.flush(cleaned)
        return ChatResponse(
            message=Message.assistant(cleaned, calls),
            finish_reason=_finish(last, bool(calls)),
            usage=_usage(last),
            model=last.get("model", self.model),
            raw=None,
        )

    def _parse(
        self, data: dict[str, Any], tools: Sequence[ToolSpec] | None
    ) -> ChatResponse:
        msg = data.get("message")
        if msg is None:
            raise BackendError(f"ollama: 응답에 message 가 없습니다: {data}")
        content = msg.get("content") or ""
        calls: list[ToolCall] = normalize_native(msg.get("tool_calls"))
        cleaned = content
        if not calls and tools:
            known = {t.name for t in tools}
            calls, cleaned = parse_prompt_toolcalls(content, known)
        return ChatResponse(
            message=Message.assistant(cleaned, calls),
            finish_reason=_finish(data, bool(calls)),
            usage=_usage(data),
            model=data.get("model", self.model),
            raw=data,
        )

    async def health(self) -> tuple[bool, str]:
        try:
            resp = await self._client.get("/api/tags")
        except httpx.HTTPError as exc:
            return False, f"{self.host} 연결 실패 (ollama serve 실행 확인): {exc}"
        if resp.status_code >= 400:
            return False, f"ollama HTTP {resp.status_code}"
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        base = self.model.split(":")[0]
        if not any(n == self.model or n.startswith(base) for n in names):
            return (
                True,
                f"연결됨. '{self.model}' 미설치 → `ollama pull {self.model}` 필요. "
                f"설치된 모델: {names[:8]}",
            )
        return True, f"연결됨 ({self.host}), '{self.model}' 확인"

    async def unload(self) -> None:
        """이 모델을 Ollama 메모리에서 즉시 내린다 (keep_alive: 0).

        앙상블·작업 분할처럼 여러 모델을 순차로 쓸 때 VRAM 을 비우는 용도.
        """
        with contextlib.suppress(httpx.HTTPError):
            await self._client.post(
                "/api/chat",
                json={"model": self.model, "messages": [], "keep_alive": 0},
            )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _usage(data: dict[str, Any]) -> Usage:
    return Usage(
        prompt_tokens=int(data.get("prompt_eval_count", 0)),
        completion_tokens=int(data.get("eval_count", 0)),
    )


def _finish(data: dict[str, Any], has_calls: bool) -> FinishReason:
    if has_calls:
        return "tool_calls"
    reason = data.get("done_reason")
    if reason == "length":
        return "length"
    return "stop"
