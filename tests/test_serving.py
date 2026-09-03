"""백엔드 어댑터 테스트 (httpx MockTransport 사용, 실제 서버 불필요)."""

import json

import httpx
import pytest

from gigachanie.serving.base import BackendError, Message, ToolSpec, run_sync
from gigachanie.serving.ollama import OllamaBackend
from gigachanie.serving.openai_compat import OpenAICompatBackend

READ_FILE = ToolSpec(
    name="read_file",
    description="파일을 읽는다",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t")


# ------------------------------------------------------------------ openai_compat


def test_openai_compat_일반응답() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/chat/completions"
        body = json.loads(req.content)
        assert body["model"] == "m"
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [
                    {"message": {"role": "assistant", "content": "안녕"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    be = OpenAICompatBackend("m", "http://t", client=_client(handler))
    resp = run_sync(be.chat([Message.user("hi")]))
    assert resp.message.content == "안녕"
    assert resp.finish_reason == "stop"
    assert resp.usage.total_tokens == 5


def test_openai_compat_툴콜() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["tools"][0]["function"]["name"] == "read_file"
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "x.py"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
        )

    be = OpenAICompatBackend("m", "http://t", client=_client(handler))
    resp = run_sync(be.chat([Message.user("read x.py")], tools=[READ_FILE]))
    assert resp.has_tool_calls
    assert resp.message.tool_calls[0].name == "read_file"
    assert resp.message.tool_calls[0].arguments == {"path": "x.py"}


def test_openai_compat_프롬프트모드_툴콜() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        # prompt 모드에서는 tools 를 API 로 넘기지 않고 시스템 프롬프트에 주입
        assert "tools" not in body
        assert "read_file" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "읽을게요\n```tool\n"
                                '{"name":"read_file","arguments":{"path":"y.py"}}\n```'
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    be = OpenAICompatBackend("m", "http://t", tool_mode="prompt", client=_client(handler))
    resp = run_sync(be.chat([Message.user("read")], tools=[READ_FILE]))
    assert resp.message.tool_calls[0].arguments == {"path": "y.py"}
    assert "```" not in resp.message.content


def test_openai_compat_http_오류() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    be = OpenAICompatBackend("m", "http://t", client=_client(handler))
    with pytest.raises(BackendError):
        run_sync(be.chat([Message.user("hi")]))


def test_openai_compat_health() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/models"
        return httpx.Response(200, json={"data": [{"id": "m"}]})

    be = OpenAICompatBackend("m", "http://t", client=_client(handler))
    ok, _ = run_sync(be.health())
    assert ok


# ------------------------------------------------------------------------ ollama


def test_ollama_일반응답_및_옵션() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/chat"
        body = json.loads(req.content)
        assert body["options"]["num_ctx"] == 8192
        assert body["keep_alive"] == "10m"
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": "네"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 4,
            },
        )

    be = OllamaBackend("qwen2.5-coder:7b", num_ctx=8192, client=_client(handler))
    resp = run_sync(be.chat([Message.user("hi")]))
    assert resp.message.content == "네"
    assert resp.usage.prompt_tokens == 10
    assert resp.finish_reason == "stop"


def test_ollama_unload() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"done": True})

    be = OllamaBackend("m", client=_client(handler))
    run_sync(be.unload())
    assert seen["body"]["keep_alive"] == 0
    assert seen["body"]["model"] == "m"


def test_reasoning_파라미터_전달() -> None:
    seen: dict = {}

    def ollama_handler(req: httpx.Request) -> httpx.Response:
        seen["ollama"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={"model": "m", "message": {"role": "assistant", "content": "x"}, "done": True},
        )

    def openai_handler(req: httpx.Request) -> httpx.Response:
        seen["openai"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [
                    {"message": {"role": "assistant", "content": "x"}, "finish_reason": "stop"}
                ],
            },
        )

    ob = OllamaBackend("m", client=_client(ollama_handler))
    run_sync(ob.chat([Message.user("hi")], reasoning="high"))
    assert seen["ollama"]["think"] == "high"

    run_sync(ob.chat([Message.user("hi")], reasoning="low-ish"))
    assert seen["ollama"]["think"] is True  # 알 수 없는 값이면 bool

    run_sync(ob.chat([Message.user("hi")]))
    assert "think" not in seen["ollama"]

    xb = OpenAICompatBackend("m", "http://t", client=_client(openai_handler))
    run_sync(xb.chat([Message.user("hi")], reasoning="low"))
    assert seen["openai"]["reasoning_effort"] == "low"


def test_ollama_툴콜_객체인자() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "m",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "read_file", "arguments": {"path": "z.py"}}}
                    ],
                },
                "done": True,
            },
        )

    be = OllamaBackend("m", client=_client(handler))
    resp = run_sync(be.chat([Message.user("read z")], tools=[READ_FILE]))
    assert resp.message.tool_calls[0].name == "read_file"
    assert resp.message.tool_calls[0].arguments == {"path": "z.py"}


def test_ollama_health_모델미설치() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

    be = OllamaBackend("qwen2.5-coder:32b", client=_client(handler))
    ok, msg = run_sync(be.health())
    assert ok
    assert "미설치" in msg
