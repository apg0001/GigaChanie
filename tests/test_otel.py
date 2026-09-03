"""선택적 OpenTelemetry (기본 비활성)."""

from __future__ import annotations

import pytest

from gigachanie.loop import otel


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(otel, "_tracer", None)
    monkeypatch.setattr(otel, "_checked", False)
    monkeypatch.delenv("GIGA_OTEL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)


def test_비활성이면_no_op() -> None:
    assert otel._get_tracer() is None
    # 예외 없이 통과해야 함
    otel.emit_run_span(name="x", started=0.0, attributes={"a": 1})


def test_활성인데_sdk_없으면_조용히_실패(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIGA_OTEL", "1")
    monkeypatch.setitem(__import__("sys").modules, "opentelemetry", None)
    assert otel._get_tracer() is None
    otel.emit_run_span(name="x", started=0.0, attributes={})
