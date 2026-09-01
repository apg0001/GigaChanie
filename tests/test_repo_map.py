"""심볼 추출 + 저장소 맵 테스트."""

from pathlib import Path

from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.context.repo_map import build_repo_map
from gigachanie.context.symbols import extract_symbols

runner = CliRunner()

_PY = '''\
"""모듈 독스트링."""

MAX_SIZE = 10


class Widget(Base):
    def __init__(self, name):
        self.name = name

    async def render(self, *args, **kw):
        return helper(self.name)


def helper(value):
    return value.upper()
'''


def test_python_심볼_추출() -> None:
    fs = extract_symbols(".py", _PY)
    names = {(s.name, s.kind) for s in fs.symbols}
    assert ("Widget", "class") in names
    assert ("render", "method") in names
    assert ("helper", "func") in names
    assert ("MAX_SIZE", "const") in names
    render = next(s for s in fs.symbols if s.name == "render")
    assert render.parent == "Widget"
    assert "*args" in render.signature and "**kw" in render.signature


def test_python_구문오류는_정규식_폴백() -> None:
    fs = extract_symbols(".py", "def broken(:\n    pass\nclass X:\n")
    # 정규식 폴백으로도 class/def 는 잡힘
    assert any(s.name == "X" for s in fs.symbols)


def test_js_심볼_추출() -> None:
    js = "export function foo() {}\nclass Bar {\n  baz() {}\n}\nexport const API_URL = 'x'\n"
    fs = extract_symbols(".ts", js)
    kinds = {(s.name, s.kind) for s in fs.symbols}
    assert ("foo", "func") in kinds
    assert ("Bar", "class") in kinds
    assert ("API_URL", "const") in kinds


def test_go_심볼_추출() -> None:
    go = "package main\n\nfunc Handler(w http.ResponseWriter) {}\ntype Server struct {\n}\n"
    fs = extract_symbols(".go", go)
    kinds = {(s.name, s.kind) for s in fs.symbols}
    assert ("Handler", "func") in kinds
    assert ("Server", "class") in kinds


_CORE = (
    "def transform(x):\n    return x + 1\n\n"
    "class Engine:\n    def run(self):\n        return transform(1)\n"
)


def _make_repo(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "core.py").write_text(_CORE, encoding="utf-8")
    # core 를 많이 참조하는 파일들 → core 랭킹 상승
    for i in range(3):
        src = (
            "from pkg.core import Engine, transform\n\n"
            f"def use{i}():\n    return Engine().run() + transform({i})\n"
        )
        (root / f"user{i}.py").write_text(src, encoding="utf-8")


def test_build_repo_map_랭킹_및_렌더(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    rm = build_repo_map(tmp_path)
    assert rm.found
    assert "저장소 맵" in rm.text
    # 가장 많이 참조되는 core.py 가 상위
    assert rm.entries[0].path == "pkg/core.py"
    assert "class Engine" in rm.text
    assert "def transform" in rm.text


def test_build_repo_map_예산_제한(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    rm = build_repo_map(tmp_path, budget_chars=120)
    assert len(rm.text) < 400
    assert "생략" in rm.text or len(rm.entries) >= 1


def test_소스없으면_빈맵(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("hi", encoding="utf-8")
    rm = build_repo_map(tmp_path)
    assert not rm.found


def test_giga_map_명령(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    result = runner.invoke(app, ["map", "-C", str(tmp_path)])
    assert result.exit_code == 0
    assert "pkg/core.py" in result.stdout

    js = runner.invoke(app, ["map", "-C", str(tmp_path), "--json"])
    assert js.exit_code == 0
    assert '"path"' in js.stdout
