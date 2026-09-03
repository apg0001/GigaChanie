"""앙상블: 여러 모델을 같은 질문에 병렬로 돌리고 판정 모델이 종합한다.

도구는 쓰지 않는다(순수 질의응답). 코드를 바꾸는 작업이 아니라 "어떻게
접근할까", "이 설계가 맞나" 같은 판단에 쓴다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from gigachanie.orchestra.multi import release
from gigachanie.serving.base import Backend, BackendError, Message

_SYS = "당신은 신중한 시니어 엔지니어입니다. 근거와 함께 간결하게 답하세요."


@dataclass
class EnsembleResult:
    answers: list[tuple[str, str]]  # (라벨, 답변 또는 오류)
    verdict: str


async def _one(label: str, backend: Backend, prompt: str) -> tuple[str, str]:
    try:
        resp = await backend.chat(
            [Message.system(_SYS), Message.user(prompt)], tools=None
        )
        return label, resp.message.content.strip() or "(빈 응답)"
    except BackendError as exc:
        return label, f"(오류: {exc})"
    finally:
        await release(backend)


async def run_ensemble(
    prompt: str,
    members: list[tuple[str, Backend]],
    judge: tuple[str, Backend],
) -> EnsembleResult:
    answers = await asyncio.gather(
        *(_one(label, be, prompt) for label, be in members)
    )
    joined = "\n\n".join(
        f"### 후보 {i + 1} ({label})\n{ans}" for i, (label, ans) in enumerate(answers)
    )
    judge_prompt = (
        f"질문:\n{prompt}\n\n"
        f"아래는 여러 모델의 답변입니다. 사실 오류·논리 허점을 걸러내고, "
        f"가장 타당한 내용을 종합해 하나의 최종 답을 작성하세요. "
        f"후보 간 의견이 갈리면 어느 쪽이 옳은지 밝히세요.\n\n{joined}"
    )
    jlabel, jbackend = judge
    try:
        resp = await jbackend.chat(
            [Message.system(_SYS), Message.user(judge_prompt)], tools=None
        )
        verdict = resp.message.content.strip() or "(판정 실패)"
    except BackendError as exc:
        verdict = f"(판정 모델 오류: {exc})"
    finally:
        await release(jbackend)
    return EnsembleResult(answers=list(answers), verdict=verdict)
