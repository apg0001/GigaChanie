"""컨텍스트 주입 예산 테스트."""

from __future__ import annotations

from gigachanie.context.budget import allocate, clip


def test_allocate_컨텍스트크기에_비례() -> None:
    small = allocate(8000)
    big = allocate(128000)
    assert big.map_chars > small.map_chars
    assert big.project_chars > small.project_chars


def test_allocate_최소치_보장() -> None:
    tiny = allocate(1000)
    assert tiny.project_chars >= 2000
    assert tiny.map_chars >= 3000
    assert tiny.memory_chars >= 1000


def test_allocate_기본값() -> None:
    assert allocate(None) == allocate(32000)


def test_clip() -> None:
    assert clip(None, 10) is None
    assert clip("짧음", 10) == "짧음"
    out = clip("x" * 100, 20)
    assert out is not None and out.startswith("x" * 20) and "잘림" in out
