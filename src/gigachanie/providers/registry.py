"""모델 레지스트리 로더.

`model_registry.yaml` 을 읽어 타입이 있는 객체로 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

_REGISTRY_FILE = "model_registry.yaml"

ToolCalling = str  # "native" | "prompt" | "none"
ModelKind = str  # "coder" | "general" | "reasoning"


@dataclass(frozen=True)
class Quant:
    """양자화 프로파일."""

    name: str
    bpw: float
    weights_gb: float


@dataclass(frozen=True)
class Model:
    """레지스트리의 모델 한 항목."""

    id: str
    display: str
    family: str
    kind: ModelKind
    params_b: float
    active_params_b: float
    context: int
    max_context: int
    tool_calling: ToolCalling
    vision: bool
    layers: int
    kv_heads: int
    head_dim: int
    license: str
    backends: tuple[str, ...]
    quants: tuple[Quant, ...]
    ollama_tag: str | None = None
    notes: str = ""

    def kv_bytes_per_token(self, kv_dtype_bytes: int = 2) -> int:
        """컨텍스트 1토큰당 KV 캐시 바이트.

        2(K,V) * layers * kv_heads * head_dim * dtype_bytes
        """
        return 2 * self.layers * self.kv_heads * self.head_dim * kv_dtype_bytes

    def quant(self, name: str) -> Quant | None:
        for q in self.quants:
            if q.name == name:
                return q
        return None

    def smallest_quant(self) -> Quant:
        return min(self.quants, key=lambda q: q.weights_gb)


@dataclass(frozen=True)
class RegistryDefaults:
    kv_dtype_bytes: int = 2
    runtime_overhead_gb: float = 1.0
    min_useful_context: int = 8192
    target_context: int = 16384


@dataclass(frozen=True)
class Registry:
    models: tuple[Model, ...]
    defaults: RegistryDefaults = field(default_factory=RegistryDefaults)

    def get(self, model_id: str) -> Model | None:
        for m in self.models:
            if m.id == model_id:
                return m
        return None

    def by_family(self, family: str) -> list[Model]:
        return [m for m in self.models if m.family == family]

    def local_capable(self) -> list[Model]:
        """로컬 백엔드(ollama / openai_compat 로컬)에서 구동 가능한 모델."""
        return [m for m in self.models if "ollama" in m.backends]


def _parse_model(raw: dict[str, Any]) -> Model:
    quants = tuple(
        Quant(name=q["name"], bpw=float(q["bpw"]), weights_gb=float(q["weights_gb"]))
        for q in raw.get("quants", [])
    )
    return Model(
        id=raw["id"],
        display=raw["display"],
        family=raw["family"],
        kind=raw["kind"],
        params_b=float(raw["params_b"]),
        active_params_b=float(raw["active_params_b"]),
        context=int(raw["context"]),
        max_context=int(raw["max_context"]),
        tool_calling=raw["tool_calling"],
        vision=bool(raw["vision"]),
        layers=int(raw["layers"]),
        kv_heads=int(raw["kv_heads"]),
        head_dim=int(raw["head_dim"]),
        license=raw["license"],
        backends=tuple(raw["backends"]),
        quants=quants,
        ollama_tag=raw.get("ollama_tag"),
        notes=raw.get("notes", ""),
    )


def load_registry(text: str | None = None) -> Registry:
    """레지스트리를 로드한다. `text` 를 주면 파일 대신 그 내용을 파싱한다(테스트용)."""
    if text is None:
        text = resources.files("gigachanie.providers").joinpath(_REGISTRY_FILE).read_text("utf-8")
    data = yaml.safe_load(text)
    raw_defaults = data.get("defaults", {})
    defaults = RegistryDefaults(
        kv_dtype_bytes=int(raw_defaults.get("kv_dtype_bytes", 2)),
        runtime_overhead_gb=float(raw_defaults.get("runtime_overhead_gb", 1.0)),
        min_useful_context=int(raw_defaults.get("min_useful_context", 8192)),
        target_context=int(raw_defaults.get("target_context", 16384)),
    )
    models = tuple(_parse_model(m) for m in data["models"])
    return Registry(models=models, defaults=defaults)


@lru_cache(maxsize=1)
def default_registry() -> Registry:
    """패키지에 포함된 기본 레지스트리 (캐시)."""
    return load_registry()
