"""`giga serve` JSON-RPC 브리지 테스트 (인메모리 스트림)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.serve import server as srvmod
from gigachanie.serve.server import PROTOCOL_VERSION, RpcServer


def _mk(monkeypatch: pytest.MonkeyPatch, backend: ScriptedBackend) -> RpcServer:
    monkeypatch.setattr(srvmod, "build_backend", lambda **_: backend)
    return RpcServer(io.StringIO(""), io.StringIO(), log=io.StringIO())


def _out(srv: RpcServer) -> list[dict]:
    assert isinstance(srv._out, io.StringIO)
    return [json.loads(x) for x in srv._out.getvalue().splitlines() if x.strip()]


def _replies(srv: RpcServer) -> dict[int, dict]:
    return {m["id"]: m for m in _out(srv) if "id" in m}


def _notes(srv: RpcServer, method: str) -> list[dict]:
    return [m["params"] for m in _out(srv) if m.get("method") == method]


def test_initialize(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _mk(monkeypatch, ScriptedBackend([]))
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    res = _replies(srv)[1]["result"]
    assert res["name"] == "gigachanie"
    assert res["protocolVersion"] == PROTOCOL_VERSION


def test_알수없는_메서드(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _mk(monkeypatch, ScriptedBackend([]))
    srv.dispatch({"jsonrpc": "2.0", "id": 9, "method": "nope", "params": {}})
    assert _replies(srv)[9]["error"]["code"] == -32601


def test_세션_생성_및_프롬프트(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = ScriptedBackend(
        [
            tool_response("read_file", {"path": "a.txt"}),
            text_response("a.txt 내용은 hi 입니다."),
        ]
    )
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    srv = _mk(monkeypatch, backend)

    srv.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/new",
            "params": {"root": str(tmp_path)},
        }
    )
    sid = _replies(srv)[1]["result"]["sessionId"]
    assert "read_file" in _replies(srv)[1]["result"]["tools"]

    srv.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/prompt",
            "params": {"sessionId": sid, "text": "a.txt 읽어줘"},
        }
    )
    sess = srv._sessions[sid]
    assert sess.worker is not None
    sess.worker.join(timeout=10)

    final = _replies(srv)[2]["result"]
    assert final["ok"] is True
    assert final["stopReason"] == "done"
    assert "hi" in final["finalText"]

    kinds = [p["kind"] for p in _notes(srv, "session/event")]
    assert "tool_call" in kinds and "done" in kinds


def test_쓰기_승인_왕복(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [
            tool_response("write_file", {"path": "new.txt", "content": "x"}),
            text_response("파일을 만들었습니다."),
        ]
    )
    srv = _mk(monkeypatch, backend)
    srv.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/new",
            "params": {"root": str(tmp_path), "write": True, "mode": "suggest"},
        }
    )
    sid = _replies(srv)[1]["result"]["sessionId"]
    srv.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/prompt",
            "params": {"sessionId": sid, "text": "new.txt 만들어줘"},
        }
    )
    sess = srv._sessions[sid]

    # 승인 요청 알림이 뜰 때까지 잠깐 기다린다.
    req = None
    for _ in range(100):
        notes = _notes(srv, "session/approval")
        if notes:
            req = notes[0]
            break
        import time

        time.sleep(0.05)
    assert req is not None and req["kind"] == "write"

    srv.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/approve",
            "params": {
                "sessionId": sid,
                "requestId": req["requestId"],
                "decision": "allow",
            },
        }
    )
    sess.worker.join(timeout=10)  # type: ignore[union-attr]

    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "x"
    assert _replies(srv)[2]["result"]["ok"] is True


def test_취소(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [tool_response("write_file", {"path": "n.txt", "content": "x"})]
    )
    srv = _mk(monkeypatch, backend)
    srv.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/new",
            "params": {"root": str(tmp_path), "write": True, "mode": "suggest"},
        }
    )
    sid = _replies(srv)[1]["result"]["sessionId"]
    srv.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/prompt",
            "params": {"sessionId": sid, "text": "만들어줘"},
        }
    )
    sess = srv._sessions[sid]
    for _ in range(100):
        if _notes(srv, "session/approval"):
            break
        import time

        time.sleep(0.05)
    srv.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/cancel",
            "params": {"sessionId": sid},
        }
    )
    sess.worker.join(timeout=10)  # type: ignore[union-attr]
    assert _replies(srv)[2]["result"]["stopReason"] == "cancelled"
    assert not (tmp_path / "n.txt").exists()


def test_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _mk(monkeypatch, ScriptedBackend([]))
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "shutdown", "params": {}})
    assert srv._running is False
