"""접근성: 색·스타일 비활성 (ui.make_console)."""

from __future__ import annotations

import pytest

from gigachanie import ui


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("NO_COLOR", "GIGA_NO_COLOR", "GIGA_PLAIN"):
        monkeypatch.delenv(k, raising=False)


def test_기본은_색_있음() -> None:
    assert ui.no_color() is False
    assert ui.plain() is False
    assert ui.make_console().no_color is False


def test_NO_COLOR_표준(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert ui.no_color() is True
    assert ui.make_console().no_color is True


def test_GIGA_NO_COLOR(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIGA_NO_COLOR", "1")
    assert ui.make_console().no_color is True


def test_GIGA_PLAIN(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIGA_PLAIN", "1")
    assert ui.plain() is True
    c = ui.make_console()
    assert c.no_color is True
    assert c._emoji is False
