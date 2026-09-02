"""@경로 참조 확장 테스트 (텍스트 · 이미지 · PDF)."""

import base64
from pathlib import Path

from gigachanie.context.refs import expand_file_refs, expand_refs

# 1x1 투명 PNG
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_참조_없으면_원문_그대로(tmp_path: Path) -> None:
    out, tfiles, imgs = expand_file_refs("그냥 질문", tmp_path)
    assert out == "그냥 질문"
    assert tfiles == [] and imgs == []


def test_파일_참조_확장(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x = 1\n", encoding="utf-8")
    out, tfiles, _ = expand_file_refs("이 @foo.py 를 봐줘", tmp_path)
    assert tfiles == ["foo.py"]
    assert "x = 1" in out and "# @foo.py" in out


def test_따옴표_경로(tmp_path: Path) -> None:
    d = tmp_path / "my dir"
    d.mkdir()
    (d / "a.txt").write_text("내용", encoding="utf-8")
    out, tfiles, _ = expand_file_refs('@"my dir/a.txt" 확인', tmp_path)
    assert tfiles == ["my dir/a.txt"]
    assert "내용" in out


def test_없는_파일은_무시(tmp_path: Path) -> None:
    out, tfiles, _ = expand_file_refs("@nope.py 어디감", tmp_path)
    assert tfiles == [] and out == "@nope.py 어디감"


def test_루트_밖_경로_차단(tmp_path: Path) -> None:
    inside = tmp_path / "inside"
    inside.mkdir()
    (tmp_path / "secret.txt").write_text("비밀", encoding="utf-8")
    r = expand_refs("@../secret.txt", inside)
    assert r.text_files == []
    assert "비밀" not in r.text
    assert any("루트 밖" in n for n in r.notes)


def test_문장부호_뒤_참조(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("A", encoding="utf-8")
    _, tfiles, _ = expand_file_refs("@a.py, 이거요", tmp_path)
    assert tfiles == ["a.py"]


def test_이미지_참조_data_uri(tmp_path: Path) -> None:
    (tmp_path / "shot.png").write_bytes(_PNG)
    r = expand_refs("이 @shot.png 화면을 설명해줘", tmp_path)
    assert r.image_files == ["shot.png"]
    assert len(r.images) == 1
    assert r.images[0].startswith("data:image/png;base64,")
    assert r.text_files == []  # 이미지는 텍스트 첨부에 안 들어감


def test_이미지_텍스트_혼합(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("code", encoding="utf-8")
    (tmp_path / "b.jpg").write_bytes(_PNG)
    r = expand_refs("@a.py 와 @b.jpg", tmp_path)
    assert r.text_files == ["a.py"]
    assert r.image_files == ["b.jpg"]


def test_pdf_pypdf_없으면_안내(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
    import gigachanie.context.refs as refsmod

    monkeypatch.setattr(refsmod, "_pdf_text", lambda _p: None)
    r = expand_refs("@doc.pdf 요약해줘", tmp_path)
    assert r.text_files == []
    assert any("PDF" in n for n in r.notes)
