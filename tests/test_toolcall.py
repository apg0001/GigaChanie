"""도구 호출 파싱 테스트."""

from gigachanie.serving.toolcall import (
    extract_first_json,
    normalize_native,
    parse_prompt_toolcalls,
)


def test_normalize_native_openai_스타일() -> None:
    raw = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
        }
    ]
    calls = normalize_native(raw)
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "a.py"}


def test_normalize_native_ollama_스타일_객체인자() -> None:
    raw = [{"function": {"name": "grep", "arguments": {"pattern": "TODO"}}}]
    calls = normalize_native(raw)
    assert calls[0].name == "grep"
    assert calls[0].arguments == {"pattern": "TODO"}
    assert calls[0].id.startswith("call_")


def test_normalize_native_빈입력() -> None:
    assert normalize_native(None) == []
    assert normalize_native([]) == []


def test_extract_first_json_prose_사이() -> None:
    text = '설명 텍스트 {"name": "x", "arguments": {"n": 1}} 뒤에 더'
    obj = extract_first_json(text)
    assert obj == {"name": "x", "arguments": {"n": 1}}


def test_extract_first_json_문자열내_중괄호() -> None:
    text = '{"msg": "a } b", "ok": true}'
    assert extract_first_json(text) == {"msg": "a } b", "ok": True}


def test_parse_prompt_toolcalls_코드블록() -> None:
    content = (
        "이 파일을 읽어볼게요.\n"
        "```tool\n"
        '{"name": "read_file", "arguments": {"path": "src/main.py"}}\n'
        "```\n"
    )
    calls, cleaned = parse_prompt_toolcalls(content)
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "src/main.py"}
    assert "```" not in cleaned
    assert "이 파일을 읽어볼게요." in cleaned


def test_parse_prompt_toolcalls_여러개() -> None:
    content = (
        "```tool\n"
        '{"name": "list_dir", "arguments": {"path": "."}}\n'
        "```\n"
        "그리고\n"
        "```tool\n"
        '{"name": "grep", "arguments": {"pattern": "def "}}\n'
        "```\n"
    )
    calls, _ = parse_prompt_toolcalls(content)
    assert [c.name for c in calls] == ["list_dir", "grep"]


def test_parse_prompt_toolcalls_tool_call_태그() -> None:
    content = '<tool_call>{"name": "run_shell", "arguments": {"cmd": "ls"}}</tool_call>'
    calls, cleaned = parse_prompt_toolcalls(content)
    assert calls[0].name == "run_shell"
    assert cleaned == ""


def test_parse_prompt_toolcalls_없음() -> None:
    calls, cleaned = parse_prompt_toolcalls("그냥 최종 답변입니다.")
    assert calls == []
    assert cleaned == "그냥 최종 답변입니다."
