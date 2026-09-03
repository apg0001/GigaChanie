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


def test_펜스없는_bare_json_복구() -> None:
    # qwen2.5-coder 가 네이티브 툴콜 대신 본문에 그냥 JSON 을 뱉는 경우
    known = {"web_search", "read_file"}
    content = '{"name": "web_search", "arguments": {"query": "임대운 교수"}}'
    calls, cleaned = parse_prompt_toolcalls(content, known)
    assert len(calls) == 1
    assert calls[0].name == "web_search"
    assert calls[0].arguments == {"query": "임대운 교수"}
    assert cleaned == ""


def test_bare_json_known_아니면_무시() -> None:
    content = '{"name": "not_a_tool", "arguments": {}}'
    calls, cleaned = parse_prompt_toolcalls(content, {"web_search"})
    assert calls == [] and cleaned == content


def test_bare_json_parameters_키_및_tool_calls_래핑() -> None:
    known = {"run_shell"}
    c1 = '{"tool": "run_shell", "parameters": {"command": "ls"}}'
    calls, _ = parse_prompt_toolcalls(c1, known)
    assert calls[0].name == "run_shell" and calls[0].arguments == {"command": "ls"}

    c2 = '{"tool_calls": [{"name": "run_shell", "arguments": {"command": "pwd"}}]}'
    calls, _ = parse_prompt_toolcalls(c2, known)
    assert calls[0].arguments == {"command": "pwd"}


def test_known_없으면_bare_json_은_답변으로() -> None:
    content = '{"name": "x", "arguments": {}}'
    calls, cleaned = parse_prompt_toolcalls(content)
    assert calls == [] and cleaned == content


def test_sh_펜스_여러_툴콜_qwen스타일() -> None:
    # qwen2.5-coder:7b 가 실제로 뱉는 형태: ```sh 펜스에 JSON 여러 개
    known = {"write_file", "apply_edit", "run_shell", "list_dir"}
    content = (
        "프로젝트를 진행합니다.\n\n"
        "```sh\n"
        '{"name": "write_file", "arguments": {"path": "a/__init__.py", "content": ""}}\n'
        '{"name": "write_file", "arguments": {"path": "a/core.py", "content": "x = 1"}}\n'
        "```\n\n"
        "이제 테스트합니다.\n"
        "```sh\n"
        '{"name": "run_shell", "arguments": {"command": "python -m pytest -q"}}\n'
        "```\n"
    )
    calls, cleaned = parse_prompt_toolcalls(content, known)
    assert [c.name for c in calls] == ["write_file", "write_file", "run_shell"]
    assert calls[1].arguments == {"path": "a/core.py", "content": "x = 1"}
    assert "write_file" not in cleaned and "run_shell" not in cleaned
    assert "프로젝트를 진행합니다" in cleaned


def test_python_펜스_예시코드는_안건드림() -> None:
    known = {"write_file", "run_shell"}
    content = "사용 예:\n```python\nresult = compute(x)\nprint(result)\n```\n끝입니다."
    calls, cleaned = parse_prompt_toolcalls(content, known)
    assert calls == [] and cleaned == content


def test_lenient_이스케이프안된_개행_복구() -> None:
    # 소형 모델이 content 에 진짜 개행을 넣어 보내는 흔한 실수
    known = {"write_file"}
    content = '{"name": "write_file", "arguments": {"content": "l1\nl2\nl3", "path": "a.txt"}}'
    calls, _ = parse_prompt_toolcalls(content, known)
    assert len(calls) == 1
    assert calls[0].arguments == {"content": "l1\nl2\nl3", "path": "a.txt"}


def test_salvage_이스케이프안된_따옴표() -> None:
    # 모델이 replace 안에 """ 를 이스케이프 없이 넣어 JSON 이 깨진 경우
    known = {"apply_edit", "write_file"}
    content = (
        '{"name": "apply_edit", "arguments": {"path": "a.py", "search": "", '
        '"replace": "def f():\n    \"\"\"doc\"\"\"\n    return 1"}}'
    )
    calls, _ = parse_prompt_toolcalls(content, known)
    assert len(calls) == 1 and calls[0].name == "apply_edit"
    assert calls[0].arguments.get("path") == "a.py"
    assert '"""doc"""' in calls[0].arguments.get("replace", "")


def test_salvage_는_known_아니면_안함() -> None:
    content = '{"name": "hallucinated", "arguments": {"path": "x", "content": "\"broken}}'
    calls, cleaned = parse_prompt_toolcalls(content, {"write_file"})
    assert calls == []
