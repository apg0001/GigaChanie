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

_TOOL_BLOCK_RE = re.compile(
    r"```(?:tool|tool_call|json)?\s*\n(?P<body>\{.*?\})\s*\n```",
    re.DOTALL,
)
# <tool_call> ... </tool_call> (일부 모델의 습관)
_TOOL_TAG_RE = re.compile(
    r"<tool_call>\s*(?P<body>\{.*?\})\s*</tool_call>",
    re.DOTALL,
)


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


def parse_prompt_toolcalls(
    content: str, known: set[str] | None = None
) -> tuple[list[ToolCall], str]:
    """본문에서 도구 호출을 추출한다.

    - ```tool``` 코드블록 / `<tool_call>` 태그
    - `known` 이 주어지면, 본문이 통째로(또는 앞부분이) `{"name": <도구>, ...}`
      JSON 인 경우도 인식 (네이티브 툴콜에 실패하고 본문에 JSON 을 뱉는 모델 대응)

    반환: (도구 호출 목록, 블록을 제거한 나머지 본문)
    """
    calls: list[ToolCall] = []
    spans: list[tuple[int, int]] = []

    for regex in (_TOOL_BLOCK_RE, _TOOL_TAG_RE):
        for m in regex.finditer(content):
            body = m.group("body")
            try:
                obj = json.loads(body)
            except json.JSONDecodeError:
                obj = extract_first_json(body)
            call = _obj_to_call(obj, None)
            if call is not None:
                calls.append(call)
                spans.append((m.start(), m.end()))

    if spans:
        spans.sort()
        cleaned_parts: list[str] = []
        cursor = 0
        for s, e in spans:
            cleaned_parts.append(content[cursor:s])
            cursor = e
        cleaned_parts.append(content[cursor:])
        return calls, "".join(cleaned_parts).strip()

    # 펜스 없이 본문에 바로 JSON 을 뱉은 경우 (known 필요)
    if known:
        stripped = content.strip()
        obj = extract_first_json(stripped)
        recovered: list[ToolCall] = []
        if isinstance(obj, list):
            recovered = [c for c in (_obj_to_call(o, known) for o in obj) if c]
        elif isinstance(obj, dict):
            inner = obj.get("tool_calls") or obj.get("tool_call")
            if isinstance(inner, list):
                recovered = [c for c in (_obj_to_call(o, known) for o in inner) if c]
            elif isinstance(inner, dict):
                one = _obj_to_call(inner, known)
                recovered = [one] if one else []
            else:
                one = _obj_to_call(obj, known)
                recovered = [one] if one else []
        if recovered:
            # 본문이 사실상 JSON 뿐이면 통째로 제거
            leftover = "" if stripped.startswith(("{", "[")) else content
            return recovered, leftover.strip()

    return [], content


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
