"""모델 레지스트리 로더 테스트."""

from gigachanie.providers.registry import default_registry, load_registry


def test_기본_레지스트리_로드() -> None:
    reg = default_registry()
    assert len(reg.models) >= 15
    ids = {m.id for m in reg.models}
    assert "qwen3-coder-30b-a3b-instruct" in ids
    assert "devstral-small-2507" in ids


def test_모든_모델_필수필드_존재() -> None:
    reg = default_registry()
    for m in reg.models:
        assert m.params_b > 0
        assert m.active_params_b > 0
        assert m.active_params_b <= m.params_b
        assert m.layers > 0 and m.kv_heads > 0 and m.head_dim > 0
        assert m.tool_calling in ("native", "prompt", "none")
        assert m.kind in ("coder", "general", "reasoning")
        assert len(m.quants) >= 1


def test_kv_캐시_계산() -> None:
    reg = default_registry()
    m = reg.get("qwen2.5-coder-32b-instruct")
    assert m is not None
    # 2 * 64 * 8 * 128 * 2 = 262144 바이트/토큰
    assert m.kv_bytes_per_token(2) == 262144


def test_get_by_family() -> None:
    reg = default_registry()
    assert len(reg.by_family("qwen")) >= 3
    assert reg.get("없는id") is None


def test_텍스트로_직접_로드() -> None:
    text = """
schema_version: 1
defaults: {}
models:
  - id: t
    display: T
    family: test
    kind: coder
    params_b: 1
    active_params_b: 1
    context: 8192
    max_context: 8192
    tool_calling: native
    vision: false
    layers: 4
    kv_heads: 2
    head_dim: 64
    license: mit
    backends: [ollama]
    ollama_tag: "t:1b"
    quants:
      - { name: q4_K_M, bpw: 4.9, weights_gb: 0.8 }
"""
    reg = load_registry(text)
    assert reg.models[0].id == "t"
    assert reg.defaults.kv_dtype_bytes == 2
