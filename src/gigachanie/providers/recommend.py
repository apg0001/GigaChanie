"""하드웨어 프로파일 + 모델 레지스트리 → 실행 가능 모델 추천.

메모리 예산을 계산하고, 각 모델의 양자화별로 확보 가능한 컨텍스트 길이를 구해
실행 가능 여부와 순위를 매긴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from gigachanie.providers.hardware import HardwareProfile
from gigachanie.providers.registry import Model, Quant, Registry, default_registry

_BYTES_PER_GB = 1024**3


class Fit(str, Enum):
    FULL = "full"  # 고품질 양자화(q8+)로 목표 컨텍스트 확보
    OK = "ok"  # q4 로 목표 컨텍스트 확보
    TIGHT = "tight"  # 최소 컨텍스트는 되지만 목표 미달
    NO = "no"  # 실행 불가

    @property
    def label(self) -> str:
        return {
            "full": "여유",
            "ok": "적합",
            "tight": "빠듯",
            "no": "불가",
        }[self.value]


class SpeedTier(str, Enum):
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"

    @property
    def label(self) -> str:
        return {"fast": "빠름", "medium": "보통", "slow": "느림"}[self.value]


@dataclass(frozen=True)
class MemoryBudget:
    """추론에 쓸 수 있는 메모리 예산."""

    usable_gb: float
    source: str  # "unified" | "vram" | "ram"
    note: str = ""


@dataclass(frozen=True)
class Recommendation:
    model: Model
    quant: Quant
    max_context: int
    fit: Fit
    speed: SpeedTier
    est_tokens_per_sec: int
    score: float
    reason: str

    @property
    def ollama_hint(self) -> str | None:
        if self.model.ollama_tag and "ollama" in self.model.backends:
            return f"ollama pull {self.model.ollama_tag}"
        return None


def compute_budget(hw: HardwareProfile) -> MemoryBudget:
    """하드웨어에서 추론용 메모리 예산(GB)을 계산한다."""
    if hw.unified_memory:
        # Apple Silicon 통합 메모리: 기본 wired 한계가 대략 전체의 70~75%.
        usable = min(hw.ram_total_gb * 0.72, hw.ram_total_gb - 6)
        return MemoryBudget(
            usable_gb=round(max(usable, 0), 1),
            source="unified",
            note="통합 메모리의 약 72%를 상한으로 가정 (iogpu.wired_limit 로 상향 가능)",
        )
    if hw.has_discrete_gpu and hw.total_vram_gb:
        usable = hw.total_vram_gb * 0.92
        return MemoryBudget(
            usable_gb=round(usable, 1),
            source="vram",
            note="VRAM의 92%를 상한으로 가정 (KV 캐시 포함, CPU 오프로딩 미고려)",
        )
    # CPU 전용
    reserve = {"Windows": 6.0, "macOS": 4.0, "Linux": 4.0}.get(hw.os_name, 5.0)
    usable = hw.ram_total_gb - reserve
    return MemoryBudget(
        usable_gb=round(max(usable, 0), 1),
        source="ram",
        note=f"GPU 미감지 → CPU 추론 가정, OS용 {reserve:.0f}GB 예약",
    )


def _max_context_for(
    model: Model, quant: Quant, budget_gb: float, reg: Registry
) -> int:
    """주어진 예산에서 이 모델+양자화로 확보 가능한 컨텍스트 토큰 수."""
    kv_per_token = model.kv_bytes_per_token(reg.defaults.kv_dtype_bytes)
    avail_for_kv_gb = budget_gb - quant.weights_gb - reg.defaults.runtime_overhead_gb
    if avail_for_kv_gb <= 0:
        return 0
    max_tokens = int(avail_for_kv_gb * _BYTES_PER_GB / kv_per_token)
    return min(max_tokens, model.max_context)


def _speed(model: Model, hw: HardwareProfile) -> tuple[SpeedTier, int]:
    """활성 파라미터와 하드웨어로 대략적인 생성 속도를 추정한다."""
    active = max(model.active_params_b, 0.5)
    if hw.unified_memory:
        tps = 180 / (active**0.85)
    elif hw.has_discrete_gpu:
        tps = 240 / (active**0.75)
    else:
        tps = 26 / active
    tps_int = max(int(tps), 1)
    if tps_int >= 30:
        return SpeedTier.FAST, tps_int
    if tps_int >= 10:
        return SpeedTier.MEDIUM, tps_int
    return SpeedTier.SLOW, tps_int


_KIND_WEIGHT = {"coder": 1.15, "reasoning": 1.05, "general": 1.0}
_TOOL_BONUS = {"native": 0.5, "prompt": 0.0, "none": -1.5}


def _quality_score(model: Model) -> float:
    size_term = math.log2(model.params_b + 1)
    return size_term * _KIND_WEIGHT.get(model.kind, 1.0) + _TOOL_BONUS.get(
        model.tool_calling, 0.0
    )


def _pick_quant_and_fit(
    model: Model, budget_gb: float, reg: Registry
) -> tuple[Quant, int, Fit] | None:
    """목표 컨텍스트를 최대한 확보하면서 품질이 가장 높은 양자화를 고른다."""
    target = reg.defaults.target_context
    min_ctx = reg.defaults.min_useful_context
    # 가중치가 큰(=품질 높은) 양자화부터 검토
    ordered = sorted(model.quants, key=lambda q: q.weights_gb, reverse=True)

    best_tight: tuple[Quant, int] | None = None
    for q in ordered:
        max_ctx = _max_context_for(model, q, budget_gb, reg)
        if max_ctx >= target:
            is_high_quant = q.bpw >= 7
            return q, max_ctx, (Fit.FULL if is_high_quant else Fit.OK)
        if max_ctx >= min_ctx and best_tight is None:
            best_tight = (q, max_ctx)

    if best_tight is not None:
        return best_tight[0], best_tight[1], Fit.TIGHT
    return None


def recommend_models(
    hw: HardwareProfile,
    reg: Registry | None = None,
    *,
    include_unfittable: bool = False,
) -> list[Recommendation]:
    """실행 가능 모델을 점수 순으로 정렬해 돌려준다."""
    reg = reg or default_registry()
    budget = compute_budget(hw)
    recs: list[Recommendation] = []

    for model in reg.models:
        local_ok = "ollama" in model.backends or "openai_compat" in model.backends
        if not local_ok:
            continue
        picked = _pick_quant_and_fit(model, budget.usable_gb, reg)
        if picked is None:
            if include_unfittable:
                q = model.smallest_quant()
                recs.append(
                    Recommendation(
                        model=model,
                        quant=q,
                        max_context=0,
                        fit=Fit.NO,
                        speed=SpeedTier.SLOW,
                        est_tokens_per_sec=0,
                        score=-999.0,
                        reason=f"메모리 부족: 최소 {q.weights_gb:.1f}GB + KV 필요, "
                        f"예산 {budget.usable_gb:.1f}GB",
                    )
                )
            continue

        quant, max_ctx, fit = picked
        speed, tps = _speed(model, hw)
        quality = _quality_score(model)
        fit_bonus = {Fit.FULL: 0.6, Fit.OK: 0.4, Fit.TIGHT: 0.0, Fit.NO: -5}[fit]
        speed_bonus = {SpeedTier.FAST: 0.5, SpeedTier.MEDIUM: 0.2, SpeedTier.SLOW: -0.3}[
            speed
        ]
        score = round(quality + fit_bonus + speed_bonus, 3)

        reason_bits = [
            f"{quant.name} 기준 컨텍스트 최대 ~{max_ctx // 1024}k",
            f"{fit.label}",
            f"속도 {speed.label}(~{tps} tok/s 추정)",
        ]
        recs.append(
            Recommendation(
                model=model,
                quant=quant,
                max_context=max_ctx,
                fit=fit,
                speed=speed,
                est_tokens_per_sec=tps,
                score=score,
                reason=", ".join(reason_bits),
            )
        )

    recs.sort(key=lambda r: r.score, reverse=True)
    return recs
