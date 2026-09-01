"""멀티 모델 오케스트레이션.

#16: 라우터 (작업 분류 → 모델 선택). #17에서 앙상블/분할/파이프라인 추가.
"""

from gigachanie.orchestra.router import (
    RouterBackend,
    TaskKind,
    classify_task,
    load_orchestra_config,
)

__all__ = [
    "RouterBackend",
    "TaskKind",
    "classify_task",
    "load_orchestra_config",
]
