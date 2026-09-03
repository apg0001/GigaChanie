"""선택적 OpenTelemetry 내보내기.

`GIGA_OTEL=1` (또는 `OTEL_EXPORTER_OTLP_ENDPOINT` 설정) + `opentelemetry-sdk`
설치 시, 에이전트 run 하나당 span 을 하나 내보낸다. 아무것도 없으면 조용히
아무 일도 하지 않는다.

    pip install "gigachanie[otel]"   # opentelemetry-sdk + otlp exporter
"""

from __future__ import annotations

import os
import time
from typing import Any

_tracer: Any = None
_checked = False


def _enabled() -> bool:
    return bool(
        os.environ.get("GIGA_OTEL") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


def _get_tracer() -> Any:
    global _tracer, _checked
    if _checked:
        return _tracer
    _checked = True
    if not _enabled():
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": "gigachanie"})
        )
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        except Exception:  # noqa: BLE001
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("gigachanie")
    except Exception:  # noqa: BLE001
        _tracer = None
    return _tracer


def emit_run_span(
    *, name: str, started: float, attributes: dict[str, Any]
) -> None:
    """이미 끝난 run 을 span 하나로 기록한다 (start=started, end=now)."""
    tracer = _get_tracer()
    if tracer is None:
        return
    try:
        span = tracer.start_span(name, start_time=int(started * 1e9))
        for k, v in attributes.items():
            if isinstance(v, str | bool | int | float):
                span.set_attribute(f"gigachanie.{k}", v)
        span.end(end_time=int(time.time() * 1e9))
    except Exception:  # noqa: BLE001
        pass
