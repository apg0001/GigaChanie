"""설정으로부터 백엔드 인스턴스를 만든다."""

from __future__ import annotations

import os
from pathlib import Path

from gigachanie.config import Config, load_config
from gigachanie.providers.registry import Registry, ToolCalling, default_registry
from gigachanie.serving.base import Backend, BackendError
from gigachanie.serving.ollama import OllamaBackend
from gigachanie.serving.openai_compat import OpenAICompatBackend


def _resolve_model_name(cfg: Config, reg: Registry) -> tuple[str, ToolCalling]:
    """(백엔드에 넘길 모델 문자열, tool_mode) 를 결정한다."""
    tool_mode: ToolCalling = "native"
    model_name = cfg.model_id or ""
    if cfg.model_id:
        entry = reg.get(cfg.model_id)
        if entry is not None:
            tool_mode = entry.tool_calling
            if cfg.backend == "ollama" and entry.ollama_tag:
                model_name = entry.ollama_tag
    return model_name, tool_mode


def _backend_from_cfg(cfg: Config, reg: Registry) -> Backend:
    model_name, tool_mode = _resolve_model_name(cfg, reg)

    if cfg.backend == "ollama":
        return OllamaBackend(
            model=model_name,
            tool_mode=tool_mode,
            num_ctx=cfg.context,
        )

    if cfg.backend == "openai_compat":
        base_url = cfg.base_url or os.environ.get("GIGA_BASE_URL")
        if not base_url:
            raise BackendError(
                "openai_compat 백엔드에는 base_url 이 필요합니다 "
                "(`giga model use <ID> --base-url http://localhost:8000/v1`)."
            )
        api_key = os.environ.get("GIGA_API_KEY") or os.environ.get("OPENAI_API_KEY")
        return OpenAICompatBackend(
            model=model_name,
            base_url=base_url,
            api_key=api_key,
            tool_mode=tool_mode,
            default_context=cfg.context,
        )

    raise BackendError(f"알 수 없는 백엔드: {cfg.backend!r} (ollama | openai_compat)")


def build_backend(
    cfg: Config | None = None,
    reg: Registry | None = None,
    *,
    root: Path | None = None,
) -> Backend:
    """현재 설정에 맞는 백엔드를 생성한다.

    `<root>/.agent/orchestra.yaml` 이 있으면 작업 분류 라우터를 반환한다.
    아니면 `giga model use` 로 선택된 단일 모델 백엔드를 반환한다.
    """
    cfg = cfg or load_config()
    reg = reg or default_registry()

    orch = _try_router(reg, root or Path.cwd(), cfg)
    if orch is not None:
        return orch

    if not cfg.model_id:
        raise BackendError(
            "선택된 모델이 없습니다. `giga model use <ID>` 또는 `giga doctor` 를 먼저 실행하세요."
        )
    return _backend_from_cfg(cfg, reg)


def build_model_backend(
    model_id: str,
    *,
    backend: str | None = None,
    base_url: str | None = None,
    context: int | None = None,
) -> Backend:
    """라우터를 거치지 않고 특정 모델 하나로 백엔드를 만든다 (앙상블·작업 분할용)."""
    base = load_config()
    return _backend_from_cfg(
        Config(
            model_id=model_id,
            backend=backend or base.backend,
            base_url=base_url or base.base_url,
            context=context or base.context,
        ),
        default_registry(),
    )


def _try_router(reg: Registry, root: Path, cfg: Config) -> Backend | None:
    from gigachanie.orchestra.router import ModelRef, RouterBackend, load_orchestra_config

    oc = load_orchestra_config(root)
    if not oc.enabled:
        return None

    def make(ref: ModelRef) -> Backend:
        return _backend_from_cfg(
            Config(
                model_id=ref.model,
                backend=ref.backend,
                base_url=ref.base_url,
                context=ref.context,
            ),
            reg,
        )

    fallback = _backend_from_cfg(cfg, reg) if cfg.model_id else None
    return RouterBackend(oc, make, fallback=fallback)
