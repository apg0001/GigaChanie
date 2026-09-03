"""도구 호출 파싱.

- 네이티브: 백엔드가 준 tool_calls 구조를 `ToolCall` 로 정규화
- 프롬프트형: 모델이 본문에 써낸 도구 호출 블록을 추출

프롬프트형 규약(시스템 프롬프트에 안내):
    도구를 쓰려면 아래 형식의 코드블록만 출력한다.
    ```tool
    {"name": "read_file", "arguments": {"path": "src/foo.py"}}
    ```
    여러 개면 블록을 여러 번 쓴다.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from gigachanie.serving.base import ToolCall

# 명시적 도구 펜스: ```tool / ```tool_call (name 검증 없이 받는다)
_TOOL_FENCE_RE = re.compile(r"```(?:tool|tool_call)\s*\n(?P<body>.*?)```", re.DOTALL)
# <tool_call> ... </tool_call> (일부 모델의 습관)
_TOOL_TAG_RE = re.compile(r"<tool_call>\s*(?P<body>.*?)\s*</tool_call>", re.DOTALL)
# 빈 코드펜스 정리용
_EMPTY_FENCE_RE = re.compile(r"```[^\n`]*\n\s*```")


_CTRL_ESCAPE = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _lenient_loads(snippet: str) -> Any | None:
    """느슨한 JSON 파서: 문자열 안의 이스케이프 안 된 개행·탭을 고쳐 재시도한다.

    소형 모델이 write_file content 에 진짜 개행을 넣어 보내는 경우가 많다.
    """
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        pass
    out: list[str] = []
    in_str = False
    esc = False
    for ch in snippet:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            elif ch == "\\":
                out.append(ch)
                esc = True
            elif ch == '"':
                out.append(ch)
                in_str = False
            elif ch in _CTRL_ESCAPE:
                out.append(_CTRL_ESCAPE[ch])
            else:
                out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_str = True
    try:
        return json.loads("".join(out))
    except json.JSONDecodeError:
        return None


def extract_all_json_spans(text: str) -> list[tuple[Any, int, int]]:
    """문자열에서 최상위 균형 JSON 객체/배열을 (값, 시작, 끝) 목록으로."""
    out: list[tuple[Any, int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch not in "{[":
            i += 1
            continue
        opener = ch
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        j = i
        matched = False
        while j < n:
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    val = _lenient_loads(text[i : j + 1])
                    if val is not None:
                        out.append((val, i, j + 1))
                    i = j + 1
                    matched = True
                    break
            j += 1
        if not matched:
            i += 1
    return out


def extract_all_json(text: str) -> list[Any]:
    return [v for v, _, _ in extract_all_json_spans(text)]


def _new_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


def _coerce_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            recovered = extract_first_json(raw)
            parsed = recovered if recovered is not None else {}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


def normalize_native(raw_calls: list[dict[str, Any]] | None) -> list[ToolCall]:
    """OpenAI / Ollama 스타일 tool_calls 리스트를 정규화한다."""
    if not raw_calls:
        return []
    calls: list[ToolCall] = []
    for item in raw_calls:
        fn = item.get("function", item)
        name = fn.get("name")
        if not name:
            continue
        calls.append(
            ToolCall(
                id=item.get("id") or _new_id(),
                name=name,
                arguments=_coerce_arguments(fn.get("arguments", {})),
            )
        )
    return calls


def extract_first_json(text: str) -> Any | None:
    """문자열에서 첫 번째 균형 잡힌 JSON 객체/배열을 찾아 파싱한다."""
    start = None
    opener = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            opener = ch
            break
    if start is None:
        return None
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                snippet = text[start : i + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    return None
    return None


def _obj_to_call(obj: Any, known: set[str] | None) -> ToolCall | None:
    """{"name": ..., "arguments": ...} 형태의 dict 를 ToolCall 로. 아니면 None."""
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("tool") or obj.get("function")
    if isinstance(name, dict):  # {"function": {"name": ...}}
        name = name.get("name")
    if not name or not isinstance(name, str):
        return None
    if known is not None and name not in known:
        return None
    args = obj.get("arguments")
    if args is None:
        args = obj.get("args")
    if args is None:
        args = obj.get("parameters")
    if args is None:
        args = obj.get("input", {})
    return ToolCall(id=_new_id(), name=name, arguments=_coerce_arguments(args))


def _calls_from_objs(objs: list[Any], known: set[str] | None) -> list[ToolCall]:
    """JSON 값 목록에서 ToolCall 을 뽑는다. {"tool_calls":[...]} 래핑도 푼다."""
    out: list[ToolCall] = []
    for o in objs:
        if isinstance(o, dict):
            inner = o.get("tool_calls") or o.get("tool_call")
            if isinstance(inner, list):
                out.extend(c for c in (_obj_to_call(x, known) for x in inner) if c)
                continue
            if isinstance(inner, dict):
                c = _obj_to_call(inner, known)
                if c:
                    out.append(c)
                continue
        if isinstance(o, list):
            out.extend(c for c in (_obj_to_call(x, known) for x in o) if c)
            continue
        c = _obj_to_call(o, known)
        if c:
            out.append(c)
    return out


def parse_prompt_toolcalls(
    content: str, known: set[str] | None = None
) -> tuple[list[ToolCall], str]:
    """본문에서 도구 호출을 추출한다.

    - 임의 언어의 코드펜스(```sh, ```json, ```tool …) / `<tool_call>` 태그 안의
      `{"name": <도구>, "arguments": {...}}` JSON (한 블록에 여러 개도 허용)
    - `known` 이 주어지면 펜스 없이 본문에 직접 쓴 JSON 도 인식
      (네이티브 툴콜에 실패하고 본문에 JSON 을 뱉는 모델 대응)

    반환: (도구 호출 목록, 블록을 제거한 나머지 본문)
    """
    calls: list[ToolCall] = []
    spans: list[tuple[int, int]] = []

    # 1) 명시적 도구 마커: ```tool / ```tool_call / <tool_call> — name 검증 없이.
    for regex in (_TOOL_FENCE_RE, _TOOL_TAG_RE):
        for m in regex.finditer(content):
            found = _calls_from_objs(extract_all_json(m.group("body")), None)
            if found:
                calls.extend(found)
                spans.append((m.start(), m.end()))

    # 2) 그 외: 본문 어디든(다른 언어의 펜스 포함) known 도구 이름과 일치하는
    #    JSON 객체를 회수. 네이티브 툴콜 실패 후 본문에 JSON 을 뱉는 모델 대응.
    if known:
        for obj, s, e in extract_all_json_spans(content):
            if any(a <= s and e <= b for a, b in spans):
                continue
            found = _calls_from_objs([obj], known)
            if found:
                calls.extend(found)
                spans.append((s, e))

    if not spans:
        return [], content

    spans.sort()
    cleaned_parts: list[str] = []
    cursor = 0
    for s, e in spans:
        if s < cursor:
            continue
        cleaned_parts.append(content[cursor:s])
        cursor = e
    cleaned_parts.append(content[cursor:])
    cleaned = _EMPTY_FENCE_RE.sub("", "".join(cleaned_parts))
    return calls, cleaned.strip()


def render_prompt_tool_docs(tools: list[dict[str, Any]] | list[Any]) -> str:
    """프롬프트형 백엔드용 도구 설명 텍스트를 만든다."""
    from gigachanie.serving.base import ToolSpec

    lines = [
        "사용 가능한 도구:",
    ]
    for t in tools:
        spec = t if isinstance(t, ToolSpec) else None
        if spec is None:
            continue
        params = json.dumps(spec.parameters.get("properties", {}), ensure_ascii=False)
        required = ", ".join(spec.parameters.get("required", []))
        lines.append(f"- {spec.name}: {spec.description}")
        lines.append(f"    파라미터: {params}")
        if required:
            lines.append(f"    필수: {required}")
    lines.append("")
    lines.append(
        "도구를 호출하려면 아래 형식의 코드블록만 출력한다. 설명 텍스트는 블록 밖에 쓴다.\n"
        "```tool\n"
        '{"name": "<도구이름>", "arguments": {<인자>}}\n'
        "```\n"
        "도구가 필요 없으면 최종 답변을 일반 텍스트로 작성한다."
    )
    return "\n".join(lines)
