"""stdio JSON-RPC 2.0 브리지.

에디터 확장(VS Code 등)이 `giga serve` 를 자식 프로세스로 띄우고
줄 단위 JSON-RPC 로 세션을 만들고 프롬프트를 보낸다. 에이전트 이벤트는
`session/event` 알림으로 스트리밍되고, 승인이 필요하면 `session/approval`
알림을 보낸 뒤 클라이언트의 `session/approve` 응답을 기다린다.

stdout 은 오직 JSON-RPC 만 나간다(로그는 stderr).
"""

from __future__ import annotations

import contextlib
import json
import queue
import sys
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from gigachanie import __version__
from gigachanie.config import load_config
from gigachanie.context import (
    MemoryStore,
    build_repo_map,
    expand_refs,
    load_project_context,
)
from gigachanie.loop.agent import Agent, AgentEvent, AgentResult
from gigachanie.loop.approval import ApprovalMode, ApprovalRequest, build_policy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.checkpoint import CheckpointStore
from gigachanie.loop.hooks import HookRunner
from gigachanie.loop.procman import ProcessManager
from gigachanie.loop.runlog import RunLogger, git_changed_files
from gigachanie.loop.tools import ToolContext
from gigachanie.permissions import load_permissions
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend

PROTOCOL_VERSION = "1"

_DEFERRED: Any = object()
_APPROVAL_TIMEOUT = 1800.0


class _Cancelled(Exception):
    pass


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _Session:
    id: str
    root: Path
    backend: Any
    writable: bool
    mode: str = "suggest"
    agent: Agent | None = None
    hooks: Any = None
    cancel: threading.Event = field(default_factory=threading.Event)
    approvals: dict[str, queue.Queue[str]] = field(default_factory=dict)
    asks: dict[str, queue.Queue[str]] = field(default_factory=dict)
    worker: threading.Thread | None = None

    def release_waiters(self) -> None:
        for q in [*self.approvals.values(), *self.asks.values()]:
            with contextlib.suppress(queue.Full):
                q.put_nowait("")


def _event_dict(sid: str, ev: AgentEvent) -> dict[str, Any]:
    d: dict[str, Any] = {"sessionId": sid, "kind": ev.kind, "step": ev.step}
    if ev.text:
        d["text"] = ev.text
    if ev.tool_name:
        d["toolName"] = ev.tool_name
    if ev.tool_args:
        d["toolArgs"] = ev.tool_args
    if ev.is_error:
        d["isError"] = True
    return d


def _result_dict(result: AgentResult, changed: list[str]) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "finalText": result.final_text,
        "stopReason": result.stop_reason,
        "steps": result.steps,
        "tokens": {
            "prompt": result.usage.prompt_tokens,
            "completion": result.usage.completion_tokens,
            "total": result.usage.total_tokens,
        },
        "changedFiles": changed,
    }


class RpcServer:
    _METHODS: dict[str, Callable[[RpcServer, dict[str, Any], Any], Any]] = {}

    def __init__(
        self,
        instream: TextIO | None = None,
        outstream: TextIO | None = None,
        *,
        log: TextIO | None = None,
    ) -> None:
        self._in = instream if instream is not None else sys.stdin
        self._out = outstream if outstream is not None else sys.stdout
        self._log = log if log is not None else sys.stderr
        self._wlock = threading.Lock()
        self._sessions: dict[str, _Session] = {}
        self._running = True

    # ------------------------------------------------------------------ io

    def _write(self, obj: dict[str, Any]) -> None:
        data = json.dumps(obj, ensure_ascii=False)
        with self._wlock:
            self._out.write(data + "\n")
            self._out.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _reply(self, mid: Any, result: dict[str, Any]) -> None:
        if mid is None:
            return
        self._write({"jsonrpc": "2.0", "id": mid, "result": result})

    def _reply_error(self, mid: Any, code: int, message: str) -> None:
        if mid is None:
            return
        self._write(
            {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
        )

    def _logline(self, msg: str) -> None:
        try:
            self._log.write(f"[giga serve] {msg}\n")
            self._log.flush()
        except (OSError, ValueError):
            pass

    # --------------------------------------------------------------- 루프

    def serve_forever(self) -> None:
        self._logline(f"준비됨 (protocol {PROTOCOL_VERSION})")
        while True:
            raw = self._in.readline()
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self._logline(f"JSON 파싱 실패: {line[:120]}")
                continue
            if isinstance(msg, dict):
                self.dispatch(msg)
            if not self._running:
                break
        for sess in list(self._sessions.values()):
            self._close_session(sess)

    def dispatch(self, msg: dict[str, Any]) -> None:
        mid = msg.get("id")
        method = str(msg.get("method", ""))
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        handler = self._METHODS.get(method)
        if handler is None:
            self._reply_error(mid, -32601, f"알 수 없는 메서드: {method}")
            return
        try:
            result = handler(self, params, mid)
        except RpcError as exc:
            self._reply_error(mid, exc.code, exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            self._logline("예외:\n" + traceback.format_exc())
            self._reply_error(mid, -32000, str(exc))
            return
        if result is _DEFERRED:
            return
        self._reply(mid, result if isinstance(result, dict) else {})

    # ----------------------------------------------------------- 세션 관리

    def _require(self, params: dict[str, Any]) -> _Session:
        sess = self._sessions.get(str(params.get("sessionId", "")))
        if sess is None:
            raise RpcError(-32602, "알 수 없는 sessionId")
        return sess

    def _make_approver(self, sess: _Session) -> Callable[[ApprovalRequest], bool]:
        def approve(req: ApprovalRequest) -> bool:
            if sess.cancel.is_set():
                return False
            rid = uuid.uuid4().hex[:12]
            q: queue.Queue[str] = queue.Queue(maxsize=1)
            sess.approvals[rid] = q
            self._notify(
                "session/approval",
                {
                    "sessionId": sess.id,
                    "requestId": rid,
                    "kind": req.kind,
                    "summary": req.summary,
                    "detail": req.detail,
                    "path": req.path,
                },
            )
            try:
                decision = q.get(timeout=_APPROVAL_TIMEOUT)
            except queue.Empty:
                return False
            finally:
                sess.approvals.pop(rid, None)
            return decision in ("allow", "always")

        return approve

    def _make_ask_user(
        self, sess: _Session
    ) -> Callable[[str, list[str], bool], str]:
        def ask(question: str, options: list[str], allow_custom: bool) -> str:
            if sess.cancel.is_set():
                return ""
            rid = uuid.uuid4().hex[:12]
            q: queue.Queue[str] = queue.Queue(maxsize=1)
            sess.asks[rid] = q
            self._notify(
                "session/ask",
                {
                    "sessionId": sess.id,
                    "requestId": rid,
                    "question": question,
                    "options": list(options),
                    "allowCustom": allow_custom,
                },
            )
            try:
                return q.get(timeout=_APPROVAL_TIMEOUT)
            except queue.Empty:
                return ""
            finally:
                sess.asks.pop(rid, None)

        return ask

    def _build_agent(
        self, sess: _Session, mode: ApprovalMode, *, web: bool, max_steps: int
    ) -> Agent:
        root = sess.root
        perms = load_permissions(root)
        pc = load_project_context(root, root)
        rm = build_repo_map(root, cwd=root)
        mem = MemoryStore(root).index_text()
        tools = build_registry(writable=sess.writable, web=web)
        policy = build_policy(
            mode,
            self._make_approver(sess),
            extra_allow_shell=perms.allow_shell,
            extra_deny_shell=perms.deny_shell,
            allow_paths=perms.allow_paths,
            deny_paths=perms.effective_deny_paths(),
        )
        hooks = HookRunner.load(root)
        sess.hooks = hooks if hooks.enabled else None
        ctx = ToolContext(
            root=root,
            policy=policy,
            checkpoints=CheckpointStore(root) if sess.writable else None,
            procman=ProcessManager(root) if sess.writable else None,
            ask_user=self._make_ask_user(sess),
            hooks=sess.hooks,
        )
        compact_at = int((load_config().context or 32000) * 0.7)
        return Agent(
            sess.backend,
            tools,
            ctx,
            project_context=pc.text if pc and pc.found else None,
            repo_map=rm.text if rm and rm.found else None,
            memory_index=mem or None,
            max_steps=max_steps,
            compact_at=compact_at,
        )

    def _close_session(self, sess: _Session) -> None:
        sess.cancel.set()
        sess.release_waiters()
        if sess.hooks is not None:
            with contextlib.suppress(Exception):
                sess.hooks.fire("stop")
        with contextlib.suppress(Exception):
            run_sync(sess.backend.close())
        if sess.agent is not None and sess.agent.ctx.procman is not None:
            sess.agent.ctx.procman.stop_all()

    # -------------------------------------------------------------- 핸들러

    def _m_initialize(self, params: dict[str, Any], mid: Any) -> dict[str, Any]:
        return {
            "name": "gigachanie",
            "version": __version__,
            "protocolVersion": PROTOCOL_VERSION,
            "cwd": str(Path.cwd()),
        }

    def _m_shutdown(self, params: dict[str, Any], mid: Any) -> dict[str, Any]:
        self._running = False
        return {"ok": True}

    def _m_session_new(self, params: dict[str, Any], mid: Any) -> dict[str, Any]:
        root = Path(str(params.get("root") or ".")).resolve()
        if not root.is_dir():
            raise RpcError(-32602, f"디렉터리가 아닙니다: {root}")
        writable = bool(params.get("write", False))
        web = bool(params.get("web", False))
        max_steps = int(params.get("maxSteps", 20) or 20)
        perms = load_permissions(root)
        try:
            mode = ApprovalMode.parse(str(params.get("mode") or perms.mode or "suggest"))
        except ValueError as exc:
            raise RpcError(-32602, str(exc)) from None
        try:
            backend = build_backend(root=root)
        except BackendError as exc:
            raise RpcError(-32000, str(exc)) from None

        sess = _Session(
            id=uuid.uuid4().hex[:12],
            root=root,
            backend=backend,
            writable=writable,
            mode=mode.value,
        )
        sess.agent = self._build_agent(sess, mode, web=web, max_steps=max_steps)
        if sess.hooks is not None:
            with contextlib.suppress(Exception):
                sess.hooks.fire("session_start")
        self._sessions[sess.id] = sess
        return {
            "sessionId": sess.id,
            "model": getattr(backend, "model", ""),
            "tools": sess.agent.tools.names(),
            "mode": mode.value,
            "writable": writable,
            "root": str(root),
        }

    def _m_session_info(self, params: dict[str, Any], mid: Any) -> dict[str, Any]:
        sess = self._require(params)
        return {
            "sessionId": sess.id,
            "model": getattr(sess.backend, "model", ""),
            "mode": sess.mode,
            "writable": sess.writable,
            "root": str(sess.root),
            "tools": sess.agent.tools.names() if sess.agent else [],
            "running": sess.worker is not None and sess.worker.is_alive(),
            "turns": sum(
                1 for m in (sess.agent.messages if sess.agent else []) if m.role == "user"
            ),
        }

    def _m_session_answer(self, params: dict[str, Any], mid: Any) -> dict[str, Any]:
        sess = self._require(params)
        rid = str(params.get("requestId", ""))
        answer = str(params.get("answer", ""))
        q = sess.asks.get(rid)
        if q is None:
            raise RpcError(-32602, "알 수 없는 requestId (만료되었을 수 있음)")
        with contextlib.suppress(queue.Full):
            q.put_nowait(answer)
        return {"ok": True}

    def _m_session_prompt(self, params: dict[str, Any], mid: Any) -> Any:
        sess = self._require(params)
        if sess.worker is not None and sess.worker.is_alive():
            raise RpcError(-32000, "이미 실행 중인 프롬프트가 있습니다.")
        text = str(params.get("text") or "")
        if not text.strip():
            raise RpcError(-32602, "text 가 비었습니다.")
        agent = sess.agent
        if agent is None:
            raise RpcError(-32000, "세션이 준비되지 않았습니다.")
        sess.cancel.clear()

        def worker() -> None:
            runlog = RunLogger(
                sess.root, task=text, model=getattr(sess.backend, "model", "")
            )

            def emit(ev: AgentEvent) -> None:
                runlog.observe(ev)
                if sess.cancel.is_set():
                    raise _Cancelled
                self._notify("session/event", _event_dict(sess.id, ev))

            try:
                exp = expand_refs(text, sess.root)
                result = run_sync(
                    agent.run(exp.text, on_event=emit, images=exp.images)
                )
                changed = git_changed_files(sess.root)
                runlog.finish(result, changed_files=changed)
                self._reply(mid, _result_dict(result, changed))
            except _Cancelled:
                self._reply(
                    mid,
                    {
                        "ok": False,
                        "finalText": "",
                        "stopReason": "cancelled",
                        "steps": 0,
                        "tokens": {},
                        "changedFiles": [],
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._logline("프롬프트 예외:\n" + traceback.format_exc())
                self._reply_error(mid, -32000, str(exc))
            finally:
                sess.worker = None

        thread = threading.Thread(
            target=worker, daemon=True, name=f"giga-serve-{sess.id}"
        )
        sess.worker = thread
        thread.start()
        return _DEFERRED

    def _m_session_cancel(self, params: dict[str, Any], mid: Any) -> dict[str, Any]:
        sess = self._require(params)
        sess.cancel.set()
        sess.release_waiters()
        return {"cancelled": True}

    def _m_session_approve(self, params: dict[str, Any], mid: Any) -> dict[str, Any]:
        sess = self._require(params)
        rid = str(params.get("requestId", ""))
        decision = str(params.get("decision", "deny"))
        q = sess.approvals.get(rid)
        if q is None:
            raise RpcError(-32602, "알 수 없는 requestId (만료되었을 수 있음)")
        with contextlib.suppress(queue.Full):
            q.put_nowait(decision)
        return {"ok": True}

    def _m_session_close(self, params: dict[str, Any], mid: Any) -> dict[str, Any]:
        sess = self._sessions.pop(str(params.get("sessionId", "")), None)
        if sess is not None:
            self._close_session(sess)
        return {"ok": True}


RpcServer._METHODS = {
    "initialize": RpcServer._m_initialize,
    "shutdown": RpcServer._m_shutdown,
    "session/new": RpcServer._m_session_new,
    "session/info": RpcServer._m_session_info,
    "session/prompt": RpcServer._m_session_prompt,
    "session/cancel": RpcServer._m_session_cancel,
    "session/approve": RpcServer._m_session_approve,
    "session/answer": RpcServer._m_session_answer,
    "session/close": RpcServer._m_session_close,
}
