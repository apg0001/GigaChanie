"""평가 하네스 테스트."""

from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.eval.harness import Check, load_tasks, run_task
from gigachanie.eval.harness import _run_check as run_check
from gigachanie.serving.base import run_sync

BUNDLED = Path(__file__).parent.parent / "src" / "gigachanie" / "eval" / "tasks"


def test_내장_태스크셋_로드() -> None:
    tasks = load_tasks(BUNDLED)
    names = {t.name for t in tasks}
    assert {"add-return-value", "create-greet", "fix-failing-test"} <= names
    assert len(tasks) >= 15  # 태스크셋 확장 (#J2)
    add = next(t for t in tasks if t.name == "add-return-value")
    assert add.checks[0].type == "file_contains"
    assert add.repo_dir is not None and add.repo_dir.is_dir()


def test_file_absent_text_판정(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def add_all(x):\n    return x\n", encoding="utf-8")
    assert run_check(Check("file_absent_text", path="m.py", text="compute_sum"), tmp_path).passed
    assert not run_check(Check("file_absent_text", path="m.py", text="add_all"), tmp_path).passed
    # 파일이 없으면 통과 (제거 성공으로 간주)
    assert run_check(Check("file_absent_text", path="gone.py", text="x"), tmp_path).passed


def test_run_check_유형들(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("return a + b\n", encoding="utf-8")
    assert run_check(Check("file_contains", path="a.py", text="a + b"), tmp_path).passed
    assert not run_check(Check("file_contains", path="a.py", text="없음"), tmp_path).passed
    assert run_check(Check("file_present", path="a.py"), tmp_path).passed
    assert run_check(Check("file_absent", path="b.py"), tmp_path).passed
    assert not run_check(Check("file_absent", path="a.py"), tmp_path).passed
    assert run_check(Check("shell", cmd="python -c \"exit(0)\""), tmp_path).passed
    assert not run_check(Check("shell", cmd="python -c \"exit(1)\""), tmp_path).passed


def test_run_task_통과() -> None:
    tasks = load_tasks(BUNDLED, ["create-greet"])
    task = tasks[0]
    backend = ScriptedBackend(
        [
            tool_response(
                "write_file",
                {"path": "greet.py", "content": 'def hello():\n    return "Hello, World!"\n'},
            ),
            text_response("greet.py 를 만들었습니다."),
        ]
    )
    result = run_sync(run_task(task, backend))
    assert result.passed
    assert result.stop_reason == "done"
    assert all(cr.passed for cr in result.checks)


def test_run_task_실패_아무것도_안하면() -> None:
    tasks = load_tasks(BUNDLED, ["add-return-value"])
    backend = ScriptedBackend([text_response("잘 모르겠습니다.")])
    result = run_sync(run_task(tasks[0], backend))
    assert not result.passed
    assert any(not cr.passed for cr in result.checks)


def test_eval_회귀_히스토리(tmp_path: Path, monkeypatch) -> None:
    import gigachanie.commands.eval as emod
    from gigachanie.eval.harness import EvalReport, TaskResult

    def _report(rate: float) -> EvalReport:
        rep = EvalReport(model="m")
        n = 10
        for i in range(n):
            rep.results.append(TaskResult(task=f"t{i}", passed=i < int(rate * n)))
        return rep

    assert emod._load_last_rate(tmp_path, "m") is None
    emod._append_history(tmp_path, "m", _report(0.8))
    assert emod._load_last_rate(tmp_path, "m") == 0.8
    emod._append_history(tmp_path, "m", _report(0.6))
    assert emod._load_last_rate(tmp_path, "m") == 0.6
    # 다른 모델은 안 섞임
    assert emod._load_last_rate(tmp_path, "other") is None


def test_run_task_편집실패_집계() -> None:
    tasks = load_tasks(BUNDLED, ["add-return-value"])
    backend = ScriptedBackend(
        [
            # 존재하지 않는 텍스트로 편집 시도 → 편집 실패
            tool_response("apply_edit", {"path": "calc.py", "search": "없는코드", "replace": "x"}),
            text_response("실패했습니다."),
        ]
    )
    result = run_sync(run_task(tasks[0], backend))
    assert result.edit_failures >= 1
    assert not result.passed
