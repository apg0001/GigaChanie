"""확장 패키지: 커스텀 명령·프롬프트를 묶어 배포·설치한다.

패키지 = 디렉터리:
    giga-ext.yaml          # name, description
    commands/*.md          # 커스텀 슬래시 명령 (→ .agent/commands/)
    prompts/*.md           # 재사용 지시문     (→ .agent/prompts/)

`giga ext install <경로>` 가 파일을 프로젝트 `.agent/` 로 복사하고
`.agent/extensions.json` 에 목록을 남긴다. MCP 서버·훅은 자동 병합하지
않고(위험) 안내만 한다.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_MANIFEST = "giga-ext.yaml"
_REGISTRY = Path(".agent") / "extensions.json"
_KINDS = ("commands", "prompts")


class ExtError(RuntimeError):
    pass


@dataclass
class ExtPackage:
    name: str
    description: str
    source: Path
    files: dict[str, list[str]] = field(default_factory=dict)  # kind -> [파일명]


def load_package(path: Path) -> ExtPackage:
    path = path.resolve()
    mf = path / _MANIFEST
    if not mf.is_file():
        raise ExtError(f"{_MANIFEST} 이 없습니다: {path}")
    try:
        data = yaml.safe_load(mf.read_text("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ExtError(f"{_MANIFEST} 파싱 실패: {exc}") from exc
    name = str(data.get("name") or path.name)
    pkg = ExtPackage(name=name, description=str(data.get("description", "")), source=path)
    for kind in _KINDS:
        d = path / kind
        if d.is_dir():
            pkg.files[kind] = sorted(f.name for f in d.glob("*.md"))
    return pkg


def _load_registry(root: Path) -> dict[str, Any]:
    p = root / _REGISTRY
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_registry(root: Path, reg: dict[str, Any]) -> None:
    p = root / _REGISTRY
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install(
    root: Path, path: Path, *, force: bool = False
) -> tuple[ExtPackage, list[str], list[str]]:
    """(패키지, 복사된 상대경로, 건너뛴 상대경로)."""
    pkg = load_package(path)
    copied: list[str] = []
    skipped: list[str] = []
    for kind, names in pkg.files.items():
        dest_dir = root / ".agent" / kind
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            dest = dest_dir / name
            rel = f".agent/{kind}/{name}"
            if dest.exists() and not force:
                skipped.append(rel)
                continue
            shutil.copy2(pkg.source / kind / name, dest)
            copied.append(rel)

    reg = _load_registry(root)
    reg[pkg.name] = {
        "description": pkg.description,
        "source": str(pkg.source),
        "files": [f".agent/{k}/{n}" for k, ns in pkg.files.items() for n in ns],
    }
    _save_registry(root, reg)
    return pkg, copied, skipped


def installed(root: Path) -> dict[str, Any]:
    return _load_registry(root)


def remove(root: Path, name: str) -> list[str]:
    reg = _load_registry(root)
    entry = reg.pop(name, None)
    if entry is None:
        raise ExtError(f"설치되지 않은 확장: {name}")
    removed: list[str] = []
    for rel in entry.get("files", []):
        f = root / rel
        if f.is_file():
            f.unlink()
            removed.append(rel)
    _save_registry(root, reg)
    return removed
