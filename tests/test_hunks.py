"""hunk 분할·선택 적용 테스트."""

from __future__ import annotations

from gigachanie.loop.hunks import apply_selected, split_hunks


def test_split_hunks_구간() -> None:
    old = "a\nb\nc\nd\ne\n"
    new = "a\nB\nc\nd\nE\n"
    hunks = split_hunks(old, new)
    assert len(hunks) == 2
    assert hunks[0].old_lines == ["b\n"] and hunks[0].new_lines == ["B\n"]
    assert hunks[1].old_lines == ["e\n"] and hunks[1].new_lines == ["E\n"]


def test_apply_selected_일부만() -> None:
    old = "a\nb\nc\nd\ne\n"
    new = "a\nB\nc\nd\nE\n"
    hunks = split_hunks(old, new)
    # 첫 번째만 수락
    assert apply_selected(old, hunks, [True, False]) == "a\nB\nc\nd\ne\n"
    # 두 번째만 수락
    assert apply_selected(old, hunks, [False, True]) == "a\nb\nc\nd\nE\n"
    # 전부
    assert apply_selected(old, hunks, [True, True]) == new
    # 아무것도
    assert apply_selected(old, hunks, [False, False]) == old


def test_추가·삭제_hunk() -> None:
    old = "keep1\ndelete_me\nkeep2\n"
    new = "keep1\nkeep2\nadded\n"
    hunks = split_hunks(old, new)
    assert len(hunks) == 2
    # 삭제만 수락, 추가는 거부
    assert apply_selected(old, hunks, [True, False]) == "keep1\nkeep2\n"
