"""초안 → 검수 파이프라인.

메인 에이전트(draft 모델)가 편집을 마친 뒤, 별도 모델(review 모델)이 그 diff 를
검토해 문제점을 낸다. `--review-fix` 면 지적사항을 draft 에이전트에 되돌려
한 번 더 수정하게 한다.

orchestra.yaml:
    models: { draft: {...}, reviewer: {...} }
    pipeline:
      review: reviewer      # models 의 슬롯 이름
      enabled: true
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gigachanie.orchestra.router import ModelRef, load_orchestra_config
from gigachanie.serving.base import Backend, BackendError, Message

_REVIEW_SYSTEM = """\
당신은 꼼꼼한 코드 리뷰어입니다. 아래 변경(diff)을 검토해 실제 문제만 지적하세요.
- 버그, 엣지케이스 누락, 회귀 위험, 명백한 스타일/규칙 위반
- 각 항목은 한 줄 불릿으로, 파일:라인 을 앞에 붙입니다
문제가 없으면 정확히 "문제 없음" 한 줄만 출력합니다.
칭찬·요약·일반론은 쓰지 않습니다.\
"""

_NO_ISSUE = "문제 없음"


@dataclass
class ReviewResult:
    text: str
    has_issues: bool
    model: str = ""

    @property
    def issue_lines(self) -> list[str]:
        if not self.has_issues:
            return []
        return [ln.strip(" -•\t") for ln in self.text.splitlines() if ln.strip()]


@dataclass
class PipelineConfig:
    review_slot: str = ""
    review_ref: ModelRef | None = None
    enabled: bool = False


def load_pipeline_config(root: Path) -> PipelineConfig:
    import yaml
    from platformdirs import user_config_path

    data: dict[str, Any] = {}
    files = [
        user_config_path("gigachanie", appauthor=False, ensure_exists=False)
        / "orchestra.yaml",
        root / ".agent" / "orchestra.yaml",
    ]
    for f in files:
        if f.is_file():
            try:
                d = yaml.safe_load(f.read_text("utf-8")) or {}
            except (OSError, yaml.YAMLError):
                d = {}
            data = {**data, **d}

    pl = data.get("pipeline") or {}
    oc = load_orchestra_config(root)
    slot = str(pl.get("review", ""))
    return PipelineConfig(
        review_slot=slot,
        review_ref=oc.models.get(slot),
        enabled=bool(pl.get("enabled", False)) and slot in oc.models,
    )


async def review_diff(
    backend: Backend,
    diff: str,
    *,
    task: str = "",
    max_diff_chars: int = 12_000,
) -> ReviewResult:
    """diff 를 검토 모델에 보내 문제점을 받는다."""
    if not diff.strip():
        return ReviewResult(text="(변경 없음)", has_issues=False, model=backend.model)

    body = diff[:max_diff_chars]
    if len(diff) > max_diff_chars:
        body += "\n… (diff 잘림)"
    user = (f"작업: {task}\n\n" if task else "") + f"변경 diff:\n```diff\n{body}\n```"

    try:
        resp = await backend.chat(
            [Message.system(_REVIEW_SYSTEM), Message.user(user)],
            tools=None,
            temperature=0.0,
        )
    except BackendError as exc:
        return ReviewResult(text=f"리뷰 실패: {exc}", has_issues=False, model=backend.model)

    text = resp.message.content.strip()
    has_issues = bool(text) and not re.match(r"^\s*문제\s*없음\s*$", text)
    return ReviewResult(
        text=text or _NO_ISSUE,
        has_issues=has_issues,
        model=resp.model or backend.model,
    )
