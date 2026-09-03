"""스펙 협업: 소형 모델이 초안, 대형 모델이 검증·보완해 최종 스펙을 만든다.

코드를 바꾸지 않는다. 설계 문서·구현 계획·API 명세처럼 "글"을 만들 때 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass

from gigachanie.orchestra.multi import release
from gigachanie.serving.base import Backend, Message

_DRAFT_SYS = (
    "너는 구현 계획 초안을 빠르게 쓰는 엔지니어다. 주어진 요구사항을 "
    "## 목표 / ## 접근 / ## 변경할 파일 / ## 단계 / ## 미해결 질문 "
    "구조의 마크다운으로 정리해라. 빠짐없이, 그러나 장황하지 않게."
)

_REVIEW_SYS = (
    "너는 시니어 리뷰어다. 아래 초안을 검토해 (1) 사실 오류·빠진 엣지 케이스·"
    "위험을 지적하고 (2) 그것을 반영한 개선된 최종본을 같은 마크다운 구조로 "
    "다시 작성해라. '## 리뷰 노트' 를 먼저, 그다음 '## 최종본' 을 낸다."
)


@dataclass
class SpecResult:
    draft: str
    final: str


async def collaborate(
    requirement: str, drafter: Backend, reviewer: Backend
) -> SpecResult:
    try:
        d = await drafter.chat(
            [Message.system(_DRAFT_SYS), Message.user(requirement)], tools=None
        )
        draft = d.message.content.strip() or "(초안 실패)"
    finally:
        await release(drafter)

    review_prompt = f"요구사항:\n{requirement}\n\n초안:\n{draft}"
    try:
        r = await reviewer.chat(
            [Message.system(_REVIEW_SYS), Message.user(review_prompt)], tools=None
        )
        final = r.message.content.strip() or "(검토 실패)"
    finally:
        await release(reviewer)

    return SpecResult(draft=draft, final=final)
