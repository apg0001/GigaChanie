"""초안→검수 파이프라인 테스트."""

from pathlib import Path

from conftest import ScriptedBackend, text_response
from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.orchestra.pipeline import load_pipeline_config, review_diff
from gigachanie.serving.base import run_sync

runner = CliRunner()

_DIFF = """\
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a - b
"""


def test_review_diff_문제있음() -> None:
    backend = ScriptedBackend([text_response("calc.py:2 add 인데 뺄셈을 함 (버그)")])
    res = run_sync(review_diff(backend, _DIFF, task="add 구현"))
    assert res.has_issues
    assert "버그" in res.text


def test_review_diff_문제없음() -> None:
    backend = ScriptedBackend([text_response("문제 없음")])
    res = run_sync(review_diff(backend, _DIFF))
    assert not res.has_issues


def test_review_diff_문제없음_사족_허용() -> None:
    # 약한 모델이 구두점·사족을 붙여도 '문제 없음' 으로 읽어야 한다
    for txt in ("문제 없음.", "문제없음", "No issues.", "문제 없음\n검토를 마쳤습니다"):
        backend = ScriptedBackend([text_response(txt)])
        res = run_sync(review_diff(backend, _DIFF))
        assert not res.has_issues, txt


def test_review_diff_문제없음이라해도_불릿있으면_문제() -> None:
    backend = ScriptedBackend(
        [text_response("문제 없음\n- calc.py:2 뺄셈 버그")]
    )
    res = run_sync(review_diff(backend, _DIFF))
    assert res.has_issues


def test_review_diff_빈변경() -> None:
    backend = ScriptedBackend([text_response("...")])
    res = run_sync(review_diff(backend, "   "))
    assert not res.has_issues
    assert "변경 없음" in res.text


def test_load_pipeline_config(tmp_path: Path) -> None:
    d = tmp_path / ".agent"
    d.mkdir()
    (d / "orchestra.yaml").write_text(
        "models:\n"
        "  drafter:  { backend: ollama, model: 'm1' }\n"
        "  reviewer: { backend: ollama, model: 'm2' }\n"
        "pipeline:\n"
        "  review: reviewer\n"
        "  enabled: true\n",
        encoding="utf-8",
    )
    pl = load_pipeline_config(tmp_path)
    assert pl.enabled
    assert pl.review_ref is not None
    assert pl.review_ref.model == "m2"


def test_pipeline_없으면_비활성(tmp_path: Path) -> None:
    assert not load_pipeline_config(tmp_path).enabled


def test_giga_review_변경없음(tmp_path: Path) -> None:
    result = runner.invoke(app, ["review", "-C", str(tmp_path)], input="")
    assert result.exit_code == 0
    assert "리뷰할 변경이 없습니다" in result.stdout
