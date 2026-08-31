"""SEARCH/REPLACE 편집 엔진 테스트."""

import pytest

from gigachanie.loop.edit import (
    EditError,
    MatchMethod,
    apply_edit,
    parse_edit_blocks,
)

SAMPLE = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"


def test_정확_일치_교체() -> None:
    res = apply_edit(SAMPLE, "    return a + b", "    return a + b + 1", file_exists=True)
    assert res.method is MatchMethod.EXACT
    assert "return a + b + 1" in res.new_content
    assert "return a - b" in res.new_content
    assert res.start_line == 2


def test_모호한_일치는_오류() -> None:
    content = "x = 1\nx = 1\n"
    with pytest.raises(EditError, match="일치"):
        apply_edit(content, "x = 1", "x = 2", file_exists=True)


def test_찾지_못하면_오류() -> None:
    with pytest.raises(EditError, match="찾지 못했"):
        apply_edit(SAMPLE, "return a * b", "return a / b", file_exists=True)


def test_줄끝_공백_무시_매칭() -> None:
    content = "line one   \nline two\n"  # 첫 줄에 trailing space
    res = apply_edit(content, "line one\nline two", "L1\nL2", file_exists=True)
    assert res.method is MatchMethod.RSTRIP
    assert res.new_content == "L1\nL2\n"


def test_들여쓰기_유연_매칭_및_재들여쓰기() -> None:
    content = "class C:\n    def m(self):\n        return 1\n"
    # search 는 들여쓰기가 다름
    res = apply_edit(
        content,
        "def m(self):\n    return 1",
        "def m(self):\n    return 2",
        file_exists=True,
    )
    assert res.method is MatchMethod.REINDENT
    assert "        return 2" in res.new_content  # 원본 들여쓰기 유지


def test_새_파일_생성() -> None:
    res = apply_edit("", "", "print('hi')", file_exists=False)
    assert res.method is MatchMethod.CREATE
    assert res.new_content == "print('hi')\n"


def test_기존_파일에_빈_search는_오류() -> None:
    with pytest.raises(EditError, match="write_file"):
        apply_edit("x", "", "y", file_exists=True)


def test_없는_파일에_비어있지않은_search는_오류() -> None:
    with pytest.raises(EditError, match="존재하지 않"):
        apply_edit("", "foo", "bar", file_exists=False)


# ------------------------------------------------------------------- 블록 파싱


def test_블록_파싱_기본() -> None:
    text = (
        "src/main.py\n"
        "<<<<<<< SEARCH\n"
        "old line\n"
        "=======\n"
        "new line\n"
        ">>>>>>> REPLACE\n"
    )
    blocks = parse_edit_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].path == "src/main.py"
    assert blocks[0].search == "old line"
    assert blocks[0].replace == "new line"


def test_블록_파싱_펜스_안에서_경로인식() -> None:
    text = (
        "```python\n"
        "src/util.py\n"
        "<<<<<<< SEARCH\n"
        "a\n"
        "=======\n"
        "b\n"
        ">>>>>>> REPLACE\n"
        "```\n"
    )
    blocks = parse_edit_blocks(text)
    assert blocks[0].path == "src/util.py"


def test_블록_파싱_여러개_경로_상속() -> None:
    text = (
        "src/a.py\n"
        "<<<<<<< SEARCH\n1\n=======\n2\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\n3\n=======\n4\n>>>>>>> REPLACE\n"
    )
    blocks = parse_edit_blocks(text)
    assert len(blocks) == 2
    assert blocks[1].path == "src/a.py"


def test_블록_없으면_오류() -> None:
    with pytest.raises(EditError):
        parse_edit_blocks("그냥 텍스트")


def test_구분선_없으면_오류() -> None:
    with pytest.raises(EditError, match="구분선"):
        parse_edit_blocks("f.py\n<<<<<<< SEARCH\nabc\n>>>>>>> REPLACE\n")
