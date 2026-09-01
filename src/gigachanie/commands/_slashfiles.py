"""커스텀 슬래시 명령: `.agent/commands/*.md` 를 `/이름` 으로 실행.

파일 형식(선택적 frontmatter):
    ---
    description: 테스트 실행하고 실패 고치기
    ---
    실패하는 테스트를 찾아서 통과시켜라. 대상: $ARGUMENTS

치환: `$ARGUMENTS` / `{{args}}` → `/이름` 뒤에 입력한 문자열.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path

_DIRS_REL = (Path(".agent") / "commands",)
_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class CustomCommand:
    name: str
    description: str
    body: str
    source: Path

    def expand(self, args: str) -> str:
        text = self.body.replace("$ARGUMENTS", args).replace("{{args}}", args)
        for i, part in enumerate(args.split(), start=1):
            text = text.replace(f"${i}", part)
        return text.strip()


def _parse(path: Path) -> CustomCommand | None:
    try:
        raw = path.read_text("utf-8", errors="replace")
    except OSError:
        return None
    desc = ""
    body = raw.strip()
    m = _FRONT_RE.match(raw)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if k.strip().lower() == "description":
                desc = v.strip()
        body = m.group(2).strip()
    if not desc:
        desc = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")[:80]
    return CustomCommand(name=path.stem, description=desc, body=body, source=path)


def load_custom_commands(root: Path) -> dict[str, CustomCommand]:
    dirs = [user_config_path("gigachanie", appauthor=False, ensure_exists=False) / "commands"]
    dirs += [root / rel for rel in _DIRS_REL]
    out: dict[str, CustomCommand] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            cmd = _parse(f)
            if cmd is not None:
                out[cmd.name] = cmd  # 뒤(프로젝트)가 사용자 것을 덮어씀
    return out
