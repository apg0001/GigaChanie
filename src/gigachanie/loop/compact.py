"""세션 대화 압축 (메모리 하네스 3층).

대화가 길어지면 오래된 메시지를 한 개의 요약 메시지로 치환한다.
시스템 프롬프트(0번)와 최근 메시지는 그대로 둔다.
"""

from __future__ import annotations

from collections.abc import Sequence

from gigachanie.serving.base import Backend, BackendError, Message, Usage

# 한/영 혼합 대략치: 문자수 / 3 + 메시지당 오버헤드
_CHARS_PER_TOKEN = 3
_MSG_OVERHEAD = 8


def estimate_tokens(messages: Sequence[Message]) -> int:
    total = 0
    for m in messages:
        total += _MSG_OVERHEAD + len(m.content) // _CHARS_PER_TOKEN
        for tc in m.tool_calls:
            total += len(str(tc.arguments)) // _CHARS_PER_TOKEN
    return total


def should_compact(messages: Sequence[Message], limit: int | None) -> bool:
    if not limit or limit <= 0:
        return False
    return estimate_tokens(messages) > limit


_SUMMARY_SYSTEM = """\
다음은 진행 중인 코딩 작업의 대화 기록이다. 이후 작업에 필요한 정보만 남겨 한국어로 간결히 요약하라.
- 사용자의 목표와 제약
- 지금까지 확인한 사실 (디렉터리 구조, 관련 파일, 발견한 버그 등)
- 수정하거나 실행한 내용과 그 결과
- 아직 해결하지 못한 것 / 다음 할 일
대화체·인사는 빼고 불릿으로만 작성한다.\
"""

_ROLE_LABEL = {"user": "사용자", "assistant": "에이전트", "tool": "도구결과", "system": "시스템"}


def _serialize(messages: Sequence[Message]) -> str:
    lines: list[str] = []
    for m in messages:
        label = _ROLE_LABEL.get(m.role, m.role)
        if m.role == "tool":
            body = m.content[:1500]
            lines.append(f"[{label}:{m.name}] {body}")
        else:
            parts = [m.content.strip()] if m.content.strip() else []
            for tc in m.tool_calls:
                parts.append(f"(도구호출 {tc.name} {tc.arguments})")
            if parts:
                lines.append(f"[{label}] " + " ".join(parts))
    return "\n".join(lines)


def _split_point(messages: list[Message], keep_recent: int) -> int:
    """시스템(0번) 이후에서, 최근 keep_recent 개를 남기는 안전한 분할 인덱스.

    분할 지점이 tool 결과 메시지 위로 떨어지지 않게(해당 assistant 호출과 분리 방지)
    앞으로 밀어 assistant/user 경계에 맞춘다.
    """
    n = len(messages)
    if n <= keep_recent + 2:
        return n
    split = n - keep_recent
    while split < n and messages[split].role == "tool":
        split += 1
    return split


async def compact(
    backend: Backend,
    messages: list[Message],
    *,
    keep_recent: int = 8,
) -> tuple[list[Message], bool, Usage]:
    """(새 메시지 목록, 압축 수행 여부, 요약 호출에 쓴 토큰)."""
    if not messages or messages[0].role != "system":
        return messages, False, Usage()

    split = _split_point(messages, keep_recent)
    if split >= len(messages):
        return messages, False, Usage()
    old = messages[1:split]
    recent = messages[split:]
    if len(old) < 2 or not recent:
        return messages, False, Usage()

    try:
        resp = await backend.chat(
            [Message.system(_SUMMARY_SYSTEM), Message.user(_serialize(old))],
            tools=None,
            temperature=0.0,
        )
    except BackendError:
        return messages, False, Usage()

    summary = resp.message.content.strip()
    if not summary:
        return messages, False, resp.usage

    summary_msg = Message.user(
        "지금까지의 대화 요약 (이전 메시지는 압축됨):\n\n" + summary
    )
    return [messages[0], summary_msg, *recent], True, resp.usage
