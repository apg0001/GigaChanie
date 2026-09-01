"""대화 세션 저장 / 재개.

`<root>/.agent/sessions/<id>.json` 에 대화(메시지)와 메타데이터를 저장한다.
`giga chat --continue` 는 가장 최근 세션을, `--resume <id>` 는 특정 세션을 이어간다.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gigachanie.serving.base import Message, ToolCall

_DIRNAME = Path(".agent") / "sessions"
_MAX_SESSIONS = 100


def _msg_to_dict(m: Message) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in m.tool_calls
        ]
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    if m.name:
        d["name"] = m.name
    return d


def _msg_from_dict(d: dict[str, Any]) -> Message:
    return Message(
        role=d.get("role", "user"),
        content=d.get("content", ""),
        tool_calls=[
            ToolCall(id=t["id"], name=t["name"], arguments=t.get("arguments", {}))
            for t in d.get("tool_calls", [])
        ],
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )


@dataclass
class SessionData:
    id: str
    title: str = ""
    model_id: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    messages: list[Message] = field(default_factory=list)

    @property
    def turns(self) -> int:
        return sum(1 for m in self.messages if m.role == "user")


class SessionStore:
    def __init__(self, root: Path) -> None:
        self._dir = (root.resolve() / _DIRNAME).resolve()

    @staticmethod
    def new_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def save(self, data: SessionData) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        data.updated = time.time()
        payload = {
            "id": data.id,
            "title": data.title,
            "model_id": data.model_id,
            "created": data.created,
            "updated": data.updated,
            "messages": [_msg_to_dict(m) for m in data.messages],
        }
        p = self._path(data.id)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        self._prune()
        return p

    def load(self, session_id: str) -> SessionData | None:
        p = self._path(session_id)
        if not p.is_file():
            return None
        try:
            d = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return SessionData(
            id=d["id"],
            title=d.get("title", ""),
            model_id=d.get("model_id", ""),
            created=d.get("created", time.time()),
            updated=d.get("updated", time.time()),
            messages=[_msg_from_dict(m) for m in d.get("messages", [])],
        )

    def list(self) -> list[SessionData]:
        if not self._dir.is_dir():
            return []
        out: list[SessionData] = []
        for p in self._dir.glob("*.json"):
            data = self.load(p.stem)
            if data is not None:
                out.append(data)
        out.sort(key=lambda s: s.updated, reverse=True)
        return out

    def latest(self) -> SessionData | None:
        sessions = self.list()
        return sessions[0] if sessions else None

    def delete(self, session_id: str) -> bool:
        p = self._path(session_id)
        if not p.is_file():
            return False
        p.unlink()
        return True

    def _prune(self) -> None:
        sessions = self.list()
        for old in sessions[_MAX_SESSIONS:]:
            self._path(old.id).unlink(missing_ok=True)
