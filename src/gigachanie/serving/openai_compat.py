"""OpenAI 호환 백엔드.

llama.cpp(server) · MLX(mlx_lm.server) · vLLM · 각종 호스팅 API 를 공통으로 다룬다.
Ollama 도 /v1 엔드포인트로 이 백엔드를 쓸 수 있으나, 전용 옵션(num_ctx, keep_alive)이
필요하면 `OllamaBackend` 를 쓴다.
"""

from __future__ import annotations

import json
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
    normalize_native,
    parse_prompt_toolcalls,
    render_prompt_tool_docs,
)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)


def _message_to_wire(msg: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": msg.role}
    if msg.role == "tool":
        out["content"] = msg.content
        out["tool_call_id"] = msg.tool_call_id or ""
        if msg.name:
            out["name"] = msg.name
        return out
    if msg.images:
        out["content"] = [
            {"type": "text", "text": msg.content},
            *(
                {"type": "image_url", "image_url": {"url": uri}}
                for uri in msg.images
            ),
        ]
    else:
        out["content"] = msg.content
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in msg.tool_calls
        ]
    return out


class OpenAICompatBackend:
    """OpenAI /chat/completions 규격 백엔드."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        api_key: str | None = None,
        tool_mode: Literal["native", "prompt", "none"] = "native",
        name: str = "openai_compat",
        default_context: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.name = name
        self.tool_mode = tool_mode
        self.base_url = base_url.rstrip("/")
        self.default_context = default_context
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, headers=headers, timeout=_DEFAULT_TIMEOUT
        )
        self._owns_client = client is None

    # ------------------------------------------------------------------ helpers

    def _build_payload(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        wire_messages = [_message_to_wire(m) for m in messages]

        if tools and self.tool_mode == "prompt":
            docs = render_prompt_tool_docs(list(tools))
            if wire_messages and wire_messages[0]["role"] == "system":
                wire_messages[0]["content"] += "\n\n" + docs
            else:
                wire_messages.insert(0, {"role": "system", "content": docs})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools and self.tool_mode == "native":
            payload["tools"] = [t.to_openai() for t in tools]
            payload["tool_choice"] = "auto"
        return payload

    # --------------------------------------------------------------------- chat

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stream_cb: StreamCallback | None = None,
    ) -> ChatResponse:
        stream = stream_cb is not None
        payload = self._build_payload(messages, tools, temperature, max_tokens, stream)

        try:
            if stream:
                return await self._chat_streaming(payload, stream_cb, tools)
            return await self._chat_once(payload, tools)
        except httpx.HTTPError as exc:
            raise BackendError(f"{self.name} 요청 실패: {exc}") from exc

    async def _chat_once(
        self, payload: dict[str, Any], tools: Sequence[ToolSpec] | None
    ) -> ChatResponse:
        resp = await self._client.post("/chat/completions", json=payload)
        if resp.status_code >= 400:
            raise BackendError(
                f"{self.name} HTTP {resp.status_code}: {resp.text[:500]}"
            )
        data = resp.json()
        return self._parse_response(data, tools)

    async def _chat_streaming(
        self,
        payload: dict[str, Any],
        stream_cb: StreamCallback | None,
        tools: Sequence[ToolSpec] | None,
    ) -> ChatResponse:
        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        model_name = self.model

        async with self._client.stream(
            "POST", "/chat/completions", json=payload
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")
                raise BackendError(f"{self.name} HTTP {resp.status_code}: {body[:500]}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:") :].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                model_name = obj.get("model", model_name)
                choices = obj.get("choices") or [{}]
                delta = choices[0].get("delta", {})
                if delta.get("content"):
                    content_parts.append(delta["content"])
                    if stream_cb:
                        stream_cb(delta["content"])
                for tc in delta.get("tool_calls", []) or []:
                    idx = tc.get("index", 0)
                    slot = tool_calls_acc.setdefault(
                        idx, {"id": None, "function": {"name": "", "arguments": ""}}
                    )
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        slot["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]
                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]

        content = "".join(content_parts)
        raw_calls = [tool_calls_acc[k] for k in sorted(tool_calls_acc)]
        calls = normalize_native(raw_calls)
        cleaned = content
        if not calls and tools and self.tool_mode == "prompt":
            calls, cleaned = parse_prompt_toolcalls(content)
        return ChatResponse(
            message=Message.assistant(cleaned, calls),
            finish_reason=_normalize_finish(finish_reason, bool(calls)),
            usage=Usage(),
            model=model_name,
            raw=None,
        )

    def _parse_response(
        self, data: dict[str, Any], tools: Sequence[ToolSpec] | None
    ) -> ChatResponse:
        choices = data.get("choices")
        if not choices:
            raise BackendError(f"{self.name}: 응답에 choices 가 없습니다: {data}")
        choice = choices[0]
        raw_msg = choice.get("message", {})
        content = raw_msg.get("content") or ""
        calls: list[ToolCall] = normalize_native(raw_msg.get("tool_calls"))

        cleaned = content
        if not calls and tools and self.tool_mode == "prompt":
            calls, cleaned = parse_prompt_toolcalls(content)

        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
        )
        return ChatResponse(
            message=Message.assistant(cleaned, calls),
            finish_reason=_normalize_finish(choice.get("finish_reason"), bool(calls)),
            usage=usage,
            model=data.get("model", self.model),
            raw=data,
        )

    # ------------------------------------------------------------------- health

    async def health(self) -> tuple[bool, str]:
        try:
            resp = await self._client.get("/models")
        except httpx.HTTPError as exc:
            return False, f"{self.base_url} 연결 실패: {exc}"
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code} at {self.base_url}/models"
        try:
            ids = [m.get("id") for m in resp.json().get("data", [])]
        except (json.JSONDecodeError, AttributeError):
            ids = []
        if ids and self.model not in ids:
            return True, f"연결됨. 단, '{self.model}' 이 목록에 없음: {ids[:8]}"
        return True, f"연결됨 ({self.base_url})"

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _normalize_finish(reason: str | None, has_calls: bool) -> FinishReason:
    if has_calls or reason == "tool_calls":
        return "tool_calls"
    if reason == "length":
        return "length"
    return "stop"
