"""@경로 참조 확장 테스트."""

from pathlib import Path

from gigachanie.context.refs import expand_file_refs


def test_참조_없으면_원문_그대로(tmp_path: Path) -> None:
    out, refs = expand_file_refs("그냥 질문", tmp_path)
    assert out == "그냥 질문"
    assert refs == []


def test_파일_참조_확장(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x = 1\n", encoding="utf-8")
    out, refs = expand_file_refs("이 @foo.py 를 봐줘", tmp_path)
    assert refs == ["foo.py"]
    assert "x = 1" in out
    assert "# @foo.py" in out


def test_따옴표_경로(tmp_path: Path) -> None:
    d = tmp_path / "my dir"
    d.mkdir()
    (d / "a.txt").write_text("내용", encoding="utf-8")
    out, refs = expand_file_refs('@"my dir/a.txt" 확인', tmp_path)
    assert refs == ["my dir/a.txt"]
    assert "내용" in out


def test_없는_파일은_무시(tmp_path: Path) -> None:
    out, refs = expand_file_refs("@nope.py 어디감", tmp_path)
    assert refs == []
    assert out == "@nope.py 어디감"


def test_루트_밖_경로_차단(tmp_path: Path) -> None:
    inside = tmp_path / "inside"
    inside.mkdir()
    (tmp_path / "secret.txt").write_text("비밀", encoding="utf-8")
    out, refs = expand_file_refs("@../secret.txt", inside)
    assert refs == []
    assert "비밀" not in out


def test_문장부호_뒤_참조(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("A", encoding="utf-8")
    out, refs = expand_file_refs("@a.py, 이거요", tmp_path)
    assert refs == ["a.py"]
