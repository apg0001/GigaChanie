"""편집 체크포인트 / 되돌리기.

에이전트 턴 단위로, 파일을 처음 수정하기 직전 내용을 스냅샷한다.
`giga undo` 는 가장 최근 턴의 스냅샷을 복원한다. git 유무와 무관하게 동작한다.

저장 위치: <root>/.agent/checkpoints/
  manifest.json   턴 목록 [{id, label, time, files: {rel: blob|"ABSENT"}}]
  blobs/<sha1>    파일 내용
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

_DIRNAME = Path(".agent") / "checkpoints"
_MANIFEST = "manifest.json"
_ABSENT = "ABSENT"
_MAX_TURNS = 50
_MAX_BLOB_BYTES = 2_000_000


@dataclass
class CheckpointTurn:
    id: str
    label: str
    time: str
    files: dict[str, str]  # rel경로 -> blob sha 또는 "ABSENT"


class CheckpointStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._dir = (self.root / _DIRNAME).resolve()
        self._blobs = self._dir / "blobs"
        self._current: CheckpointTurn | None = None

    # ------------------------------------------------------------- manifest

    def _load(self) -> list[CheckpointTurn]:
        mf = self._dir / _MANIFEST
        if not mf.is_file():
            return []
        try:
            data = json.loads(mf.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [
            CheckpointTurn(id=t["id"], label=t["label"], time=t["time"], files=t["files"])
            for t in data
        ]

    def _save(self, turns: list[CheckpointTurn]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = [
            {"id": t.id, "label": t.label, "time": t.time, "files": t.files}
            for t in turns[-_MAX_TURNS:]
        ]
        (self._dir / _MANIFEST).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ------------------------------------------------------------- 턴

    def open_turn(self, label: str) -> None:
        self._current = CheckpointTurn(
            id=hashlib.sha1(f"{label}{time.time()}".encode()).hexdigest()[:12],
            label=label[:80],
            time=time.strftime("%Y-%m-%d %H:%M:%S"),
            files={},
        )

    def close_turn(self) -> None:
        if self._current is None or not self._current.files:
            self._current = None
            return
        turns = self._load()
        turns.append(self._current)
        self._save(turns)
        self._current = None

    def before_write(self, path: Path) -> None:
        """path 를 수정하기 직전 호출. 현재 턴에서 처음이면 스냅샷."""
        if self._current is None:
            return
        try:
            rel = path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return
        if rel in self._current.files:
            return
        if path.is_file():
            data = path.read_bytes()
            if len(data) > _MAX_BLOB_BYTES:
                return
            sha = hashlib.sha1(data).hexdigest()
            self._blobs.mkdir(parents=True, exist_ok=True)
            blob = self._blobs / sha
            if not blob.exists():
                blob.write_bytes(data)
            self._current.files[rel] = sha
        else:
            self._current.files[rel] = _ABSENT

    # ------------------------------------------------------------- 복원

    def history(self) -> list[CheckpointTurn]:
        return list(reversed(self._load()))

    def undo(self) -> tuple[str, list[str]] | None:
        """가장 최근 턴을 복원. (라벨, 복원된 파일 목록) 또는 None."""
        turns = self._load()
        if not turns:
            return None
        turn = turns.pop()
        restored: list[str] = []
        for rel, ref in turn.files.items():
            target = self.root / rel
            if ref == _ABSENT:
                if target.is_file():
                    target.unlink()
                    restored.append(rel + " (삭제)")
            else:
                blob = self._blobs / ref
                if blob.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(blob.read_bytes())
                    restored.append(rel)
        self._save(turns)
        return turn.label, restored
