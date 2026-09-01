"""오케스트레이션 라우터 테스트."""

from pathlib import Path

from conftest import ScriptedBackend, text_response
from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.orchestra.router import (
    ModelRef,
    RouterBackend,
    TaskKind,
    classify_task,
    load_orchestra_config,
)
from gigachanie.serving.base import Message, run_sync

runner = CliRunner()


def test_classify_task() -> None:
    assert classify_task("이 오타를 고쳐줘") is TaskKind.TYPO
    assert classify_task("add 함수에 타입 힌트를 추가해줘") is TaskKind.SIMPLE_EDIT
    assert classify_task("이 버그를 고쳐줘, 에러가 나") is TaskKind.DEBUG
    assert classify_task("이 모듈을 리팩터링해줘") is TaskKind.REFACTOR
    assert classify_task("인증을 어떻게 설계해야 할까?") is TaskKind.DESIGN
    assert classify_task("test_foo 에 테스트 추가해줘") is TaskKind.TEST
    assert classify_task("안녕") is TaskKind.GENERAL


def _cfg(tmp_path: Path, body: str) -> None:
    d = tmp_path / ".agent"
    d.mkdir(exist_ok=True)
    (d / "orchestra.yaml").write_text(body, encoding="utf-8")


ORCH = """
models:
  fast:  { backend: ollama, model: "qwen2.5-coder:7b" }
  heavy: { backend: ollama, model: "qwen2.5-coder:32b" }
router:
  rules:
    simple_edit: fast
    typo: fast
    debug: heavy
  default: heavy
"""


def test_load_orchestra_config(tmp_path: Path) -> None:
    _cfg(tmp_path, ORCH)
    oc = load_orchestra_config(tmp_path)
    assert oc.enabled
    assert oc.default == "heavy"
    assert oc.route(TaskKind.TYPO).model == "qwen2.5-coder:7b"
    assert oc.route(TaskKind.DEBUG).model == "qwen2.5-coder:32b"
    assert oc.route(TaskKind.GENERAL).model == "qwen2.5-coder:32b"  # default


def test_설정없으면_비활성(tmp_path: Path) -> None:
    assert not load_orchestra_config(tmp_path).enabled


def test_router_backend_첫메시지로_라우팅(tmp_path: Path) -> None:
    _cfg(tmp_path, ORCH)
    oc = load_orchestra_config(tmp_path)
    made: list[str] = []

    def make(ref: ModelRef):
        made.append(ref.model)
        return ScriptedBackend([text_response("ok"), text_response("ok2")])

    rb = RouterBackend(oc, make)
    run_sync(rb.chat([Message.user("이 오타 고쳐줘")]))
    assert made == ["qwen2.5-coder:7b"]  # typo → fast
    assert "typo" in rb.last_route
    # 두 번째 호출은 같은 백엔드 재사용
    run_sync(rb.chat([Message.user("또 다른 것")]))
    assert made == ["qwen2.5-coder:7b"]


def test_router_default_fallback(tmp_path: Path) -> None:
    _cfg(tmp_path, ORCH)
    oc = load_orchestra_config(tmp_path)
    made: list[str] = []

    def make(ref: ModelRef):
        made.append(ref.model)
        return ScriptedBackend([text_response("ok")])

    rb = RouterBackend(oc, make)
    run_sync(rb.chat([Message.user("설계를 어떻게 할까 고민이야")]))
    assert made == ["qwen2.5-coder:32b"]  # design → 규칙 없음 → default heavy


def test_giga_route_cli(tmp_path: Path) -> None:
    _cfg(tmp_path, ORCH)
    result = runner.invoke(
        app, ["route", "이", "버그를", "고쳐줘", "-C", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "debug" in result.stdout
    assert "qwen2.5-coder:32b" in result.stdout

    no_cfg = runner.invoke(app, ["route", "-C", str(tmp_path / "empty")])
    assert no_cfg.exit_code == 1
