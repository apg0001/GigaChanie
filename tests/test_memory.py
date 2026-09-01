"""장기 메모리 저장소 + 도구 + CLI 테스트."""

from pathlib import Path

from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.context.memory import MemoryStore
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import run_sync

runner = CliRunner()


def test_add_list_get(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    e = store.add("빌드 명령", "빌드는 make build 로 한다.", ["build"])
    assert e.slug == "빌드-명령"
    assert (tmp_path / ".agent" / "memory" / "빌드-명령.md").is_file()
    assert (tmp_path / ".agent" / "memory" / "INDEX.md").is_file()

    entries = store.all_entries()
    assert len(entries) == 1
    assert entries[0].tags == ["build"]
    assert store.get("빌드-명령").body.startswith("빌드는 make")


def test_slug_중복_처리(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    a = store.add("메모", "첫째")
    b = store.add("메모", "둘째")
    assert a.slug != b.slug
    assert b.slug == "메모-2"


def test_search_토큰겹침(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.add("배포 절차", "배포는 deploy.sh 실행", ["deploy"])
    store.add("테스트 규칙", "pytest 로 돌린다", ["test"])
    hits = store.search("deploy 배포")
    assert hits and hits[0].slug == "배포-절차"
    assert store.search("전혀관계없는쿼리xyz") == []


def test_remove(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.add("삭제될것", "내용")
    assert store.remove("삭제될것") is True
    assert store.remove("삭제될것") is False
    assert store.all_entries() == []


def test_index_text_주입형식(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.add("규칙 하나", "커밋 메시지는 한국어", ["git"])
    text = store.index_text()
    assert "read_memory" in text
    assert "규칙-하나" in text
    assert "커밋 메시지는 한국어" in text


def test_read_memory_도구(tmp_path: Path) -> None:
    MemoryStore(tmp_path).add("아키텍처", "레이어는 6개다", ["arch"])
    tool = build_registry().get("read_memory")
    assert tool is not None
    ctx = ToolContext(root=tmp_path)
    res = run_sync(tool.run({"slug": "아키텍처"}, ctx))
    assert "레이어는 6개다" in res.content
    miss = run_sync(tool.run({"slug": "없음"}, ctx))
    assert miss.is_error


def test_save_memory_도구_승인(tmp_path: Path) -> None:
    reg = build_registry(writable=True)
    tool = reg.get("save_memory")
    assert tool is not None

    denied = ToolContext(
        root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.SUGGEST, approver=lambda _r: False)
    )
    res = run_sync(tool.run({"title": "X", "body": "Y"}, denied))
    assert res.is_error
    assert not (tmp_path / ".agent" / "memory").exists()

    ok = ToolContext(root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO))
    res = run_sync(tool.run({"title": "결정", "body": "SQLite 를 쓴다", "tags": "db"}, ok))
    assert not res.is_error
    assert MemoryStore(tmp_path).get("결정").body == "SQLite 를 쓴다"


def test_giga_memory_cli(tmp_path: Path) -> None:
    add = runner.invoke(
        app,
        ["memory", "add", "규칙", "-b", "테스트는 pytest", "-t", "test,ci", "-C", str(tmp_path)],
    )
    assert add.exit_code == 0

    lst = runner.invoke(app, ["memory", "list", "-C", str(tmp_path)])
    assert lst.exit_code == 0 and "규칙" in lst.stdout

    show = runner.invoke(app, ["memory", "show", "규칙", "-C", str(tmp_path)])
    assert show.exit_code == 0 and "pytest" in show.stdout

    rm = runner.invoke(app, ["memory", "rm", "규칙", "-C", str(tmp_path)])
    assert rm.exit_code == 0
