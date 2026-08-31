"""모델 추천 로직 테스트."""

from gigachanie.providers.hardware import GPU, Backend, HardwareProfile
from gigachanie.providers.recommend import Fit, compute_budget, recommend_models


def _mac_32gb() -> HardwareProfile:
    return HardwareProfile(
        os_name="macOS",
        os_version="14.5",
        arch="arm64",
        cpu_brand="Apple M2 Pro",
        cpu_cores_physical=10,
        cpu_cores_logical=10,
        ram_total_gb=32.0,
        ram_available_gb=20.0,
        is_apple_silicon=True,
        unified_memory=True,
        gpus=(GPU(name="Apple M2 Pro", vram_gb=32.0, vendor="apple"),),
        backends=(Backend(name="ollama", available=True),),
    )


def _cpu_only_16gb() -> HardwareProfile:
    return HardwareProfile(
        os_name="Windows",
        os_version="11",
        arch="AMD64",
        cpu_brand="Intel i7",
        cpu_cores_physical=8,
        cpu_cores_logical=16,
        ram_total_gb=16.0,
        ram_available_gb=9.0,
        is_apple_silicon=False,
        unified_memory=False,
        gpus=(),
        backends=(Backend(name="ollama", available=True),),
    )


def _gpu_24gb() -> HardwareProfile:
    return HardwareProfile(
        os_name="Linux",
        os_version="6.1",
        arch="x86_64",
        cpu_brand="Ryzen 9",
        cpu_cores_physical=12,
        cpu_cores_logical=24,
        ram_total_gb=64.0,
        ram_available_gb=50.0,
        is_apple_silicon=False,
        unified_memory=False,
        gpus=(GPU(name="RTX 4090", vram_gb=24.0, vendor="nvidia"),),
        backends=(Backend(name="ollama", available=True),),
    )


def test_예산_계산_apple_통합메모리() -> None:
    b = compute_budget(_mac_32gb())
    assert b.source == "unified"
    assert 22 <= b.usable_gb <= 24


def test_예산_계산_cpu_전용() -> None:
    b = compute_budget(_cpu_only_16gb())
    assert b.source == "ram"
    assert b.usable_gb == 10.0


def test_예산_계산_vram() -> None:
    b = compute_budget(_gpu_24gb())
    assert b.source == "vram"
    assert 21 <= b.usable_gb <= 23


def test_mac_32gb_추천_상위권에_30b_a3b() -> None:
    recs = recommend_models(_mac_32gb())
    assert recs
    top_ids = [r.model.id for r in recs[:3]]
    assert "qwen3-coder-30b-a3b-instruct" in top_ids
    assert all(r.fit != Fit.NO for r in recs)


def test_대형모델은_로컬추천에서_제외되거나_불가() -> None:
    recs = recommend_models(_mac_32gb(), include_unfittable=True)
    kimi = next((r for r in recs if r.model.id == "kimi-k2-instruct"), None)
    # openai_compat 전용이지만 include_unfittable 시 목록에는 등장, fit=NO
    if kimi is not None:
        assert kimi.fit == Fit.NO


def test_cpu_16gb_에서는_32b_불가() -> None:
    recs = recommend_models(_cpu_only_16gb(), include_unfittable=True)
    big = next(r for r in recs if r.model.id == "qwen2.5-coder-32b-instruct")
    assert big.fit == Fit.NO


def test_추천_점수_내림차순_정렬() -> None:
    recs = recommend_models(_gpu_24gb())
    scores = [r.score for r in recs]
    assert scores == sorted(scores, reverse=True)
