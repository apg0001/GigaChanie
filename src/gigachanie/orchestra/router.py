"""작업 분류 라우터.

첫 사용자 메시지를 규칙으로 분류(TaskKind)하고, `orchestra.yaml` 의 매핑에 따라
그 세션에 쓸 백엔드를 고른다. 분류에 실패하면 default 모델을 쓴다.

orchestra.yaml (사용자 `~/.config/gigachanie/` < 프로젝트 `<root>/.agent/`):
    models:
      fast:  { backend: ollama, model: "qwen2.5-coder-7b-instruct" }
      heavy: { backend: ollama, model: "qwen2.5-coder-32b-instruct" }
    router:
      rules:
        simple_edit: fast
        typo: fast
        debug: heavy
        design: heavy
        refactor: heavy
      default: heavy
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from platformdirs import user_config_path

from gigachanie.serving.base import (
    Backend,
    ChatResponse,
    Message,
    StreamCallback,
    ToolSpec,
)

_USER_FILE = (
    user_config_path("gigachanie", appauthor=False, ensure_exists=False)
    / "orchestra.yaml"
)
_PROJECT_REL = Path(".agent") / "orchestra.yaml"


class TaskKind(str, Enum):
    TYPO = "typo"
    SIMPLE_EDIT = "simple_edit"
    DEBUG = "debug"
    DESIGN = "design"
    REFACTOR = "refactor"
    TEST = "test"
    GENERAL = "general"


# (정규식, 분류) — 위에서부터 먼저 맞는 것
_RULES: list[tuple[re.Pattern[str], TaskKind]] = [
    (re.compile(r"오타|typo|철자|맞춤법"), TaskKind.TYPO),
    (re.compile(r"리팩터|리팩토링|refactor|구조\s*개선|정리해|추출해"), TaskKind.REFACTOR),
    (
        re.compile(
            r"버그|고쳐|디버그|debug|안\s*돼|에러|exception|실패하는|crash"
        ),
        TaskKind.DEBUG,
    ),
    (
        re.compile(
            r"설계|아키텍처|design|어떻게\s*(해야|하면)|방법|전략|계획\s*세워|비교해"
        ),
        TaskKind.DESIGN,
    ),
    (re.compile(r"테스트\s*(추가|작성|짜)|test\s*(추가|작성)|커버리지"), TaskKind.TEST),
    (
        re.compile(
            r"추가해|바꿔|수정해|이름\s*바꿔|rename|한\s*줄|타입\s*힌트|주석\s*(추가|달)|"
            r"import\s*정리|포맷"
        ),
        TaskKind.SIMPLE_EDIT,
    ),
]


def classify_task(text: str) -> TaskKind:
    """사용자 지시문을 규칙으로 분류한다."""
    t = text.strip()
    if len(t) <= 60 and re.search(r"오타|typo|한\s*줄|rename|이름\s*바꿔", t):
        return TaskKind.TYPO
    for pattern, kind in _RULES:
        if pattern.search(t):
            return kind
    return TaskKind.GENERAL


# --------------------------------------------------------------- 설정


@dataclass
class ModelRef:
    backend: str
    model: str
    base_url: str | None = None
    context: int | None = None


@dataclass
class OrchestraConfig:
    models: dict[str, ModelRef] = field(default_factory=dict)
    rules: dict[str, str] = field(default_factory=dict)  # TaskKind -> models 키
    default: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.models and self.default)

    def route(self, kind: TaskKind) -> ModelRef | None:
        name = self.rules.get(kind.value) or self.default
        return self.models.get(name)


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text("utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def load_orchestra_config(root: Path) -> OrchestraConfig:
    data: dict[str, Any] = {}
    for src in (_USER_FILE, root / _PROJECT_REL):
        d = _read(src)
        if d:
            data = {**data, **d}
    cfg = OrchestraConfig()
    for name, ref in (data.get("models") or {}).items():
        cfg.models[name] = ModelRef(
            backend=ref.get("backend", "ollama"),
            model=ref["model"],
            base_url=ref.get("base_url"),
            context=ref.get("context"),
        )
    router = data.get("router") or {}
    cfg.rules = {str(k): str(v) for k, v in (router.get("rules") or {}).items()}
    cfg.default = str(router.get("default", "")) or next(iter(cfg.models), "")
    return cfg


# --------------------------------------------------------------- 백엔드


BackendFactory = Any  # Callable[[ModelRef], Backend]


class RouterBackend(Backend):
    """첫 사용자 메시지를 분류해 백엔드를 선택하고, 그 세션 동안 위임한다."""

    def __init__(
        self,
        cfg: OrchestraConfig,
        make_backend: BackendFactory,
        *,
        fallback: Backend | None = None,
    ) -> None:
        self._cfg = cfg
        self._make = make_backend
        self._fallback = fallback
        self._active: Backend | None = fallback
        self._route_note = ""
        self.name = "router"

    @property
    def model(self) -> str:
        return self._active.model if self._active else "(미결정)"

    @property
    def tool_mode(self) -> Literal["native", "prompt", "none"]:
        return self._active.tool_mode if self._active else "native"

    @property
    def last_route(self) -> str:
        return self._route_note

    def _ensure(self, messages: Sequence[Message]) -> Backend:
        if self._active is not None and self._route_note:
            return self._active
        first_user = next((m.content for m in messages if m.role == "user"), "")
        kind = classify_task(first_user)
        ref = self._cfg.route(kind)
        if ref is None:
            self._route_note = f"{kind.value} → (기본 백엔드)"
            if self._active is None:
                raise RuntimeError("라우팅할 모델이 없고 fallback 도 없습니다.")
            return self._active
        self._active = self._make(ref)
        self._route_note = f"{kind.value} → {ref.model}"
        return self._active

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stream_cb: StreamCallback | None = None,
    ) -> ChatResponse:
        backend = self._ensure(messages)
        return await backend.chat(
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
            stream_cb=stream_cb,
        )

    async def health(self) -> tuple[bool, str]:
        if self._active is None:
            return True, f"라우터 (모델 {len(self._cfg.models)}개, 아직 미결정)"
        ok, msg = await self._active.health()
        return ok, f"[{self._route_note or '기본'}] {msg}"

    async def close(self) -> None:
        if self._active is not None:
            await self._active.close()
        if self._fallback is not None and self._fallback is not self._active:
            await self._fallback.close()
