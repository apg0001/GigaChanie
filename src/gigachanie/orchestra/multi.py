"""앙상블·작업 분할 공용 헬퍼: 모델 지정을 백엔드로 푼다."""

from __future__ import annotations

from pathlib import Path

from gigachanie.orchestra.router import load_orchestra_config
from gigachanie.serving.base import Backend
from gigachanie.serving.factory import build_model_backend


def resolve_backend(spec: str, root: Path) -> tuple[str, Backend]:
    """`spec` 은 orchestra.yaml 슬롯 이름 또는 모델 ID. (표시 라벨, 백엔드) 반환."""
    oc = load_orchestra_config(root)
    ref = oc.models.get(spec)
    if ref is not None:
        return f"{spec}={ref.model}", build_model_backend(
            ref.model, backend=ref.backend, base_url=ref.base_url, context=ref.context
        )
    return spec, build_model_backend(spec)


def default_specs(root: Path) -> list[str]:
    """--model 을 안 줬을 때 쓸 기본 목록: orchestra.yaml 슬롯 전체."""
    return list(load_orchestra_config(root).models.keys())


async def release(backend: Backend) -> None:
    """모델을 메모리에서 내리고(가능하면) 클라이언트를 닫는다.

    앙상블·작업 분할·스펙 협업처럼 여러 모델을 순차로 쓸 때 호출한다.
    """
    import contextlib

    unload = getattr(backend, "unload", None)
    if callable(unload):
        with contextlib.suppress(Exception):
            await unload()
    await backend.close()
