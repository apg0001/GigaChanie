"""확장 패키지(giga ext) 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from gigachanie import extpack
from gigachanie.cli import app

runner = CliRunner()


def _pkg(tmp_path: Path) -> Path:
    src = tmp_path / "mypack"
    (src / "commands").mkdir(parents=True)
    (src / "prompts").mkdir(parents=True)
    (src / "giga-ext.yaml").write_text("name: mypack\ndescription: 테스트 팩\n", encoding="utf-8")
    (src / "commands" / "hi.md").write_text("인사해라", encoding="utf-8")
    (src / "prompts" / "style.md").write_text("간결하게", encoding="utf-8")
    return src


def test_load_package(tmp_path: Path) -> None:
    pkg = extpack.load_package(_pkg(tmp_path))
    assert pkg.name == "mypack" and pkg.description == "테스트 팩"
    assert pkg.files == {"commands": ["hi.md"], "prompts": ["style.md"]}


def test_install_and_list_and_remove(tmp_path: Path) -> None:
    src = _pkg(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()

    pkg, copied, skipped = extpack.install(proj, src)
    assert set(copied) == {".agent/commands/hi.md", ".agent/prompts/style.md"}
    assert (proj / ".agent" / "commands" / "hi.md").read_text(encoding="utf-8") == "인사해라"
    assert "mypack" in extpack.installed(proj)

    # 재설치 → skip
    _, copied2, skipped2 = extpack.install(proj, src)
    assert copied2 == [] and len(skipped2) == 2

    removed = extpack.remove(proj, "mypack")
    assert len(removed) == 2
    assert not (proj / ".agent" / "commands" / "hi.md").exists()
    assert "mypack" not in extpack.installed(proj)


def test_manifest_없으면_오류(tmp_path: Path) -> None:
    with pytest.raises(extpack.ExtError):
        extpack.load_package(tmp_path)


def test_cli(tmp_path: Path) -> None:
    src = _pkg(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    r = runner.invoke(app, ["ext", "install", str(src), "-C", str(proj)])
    assert r.exit_code == 0 and "mypack" in r.stdout
    r = runner.invoke(app, ["ext", "list", "-C", str(proj)])
    assert "mypack" in r.stdout
    r = runner.invoke(app, ["ext", "remove", "mypack", "-C", str(proj)])
    assert r.exit_code == 0
