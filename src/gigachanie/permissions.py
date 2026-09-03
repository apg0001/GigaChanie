"""권한 설정 로드·병합.

우선순위: 내장 기본값 < 사용자(`~/.config/gigachanie/permissions.yaml`)
        < 프로젝트(`<root>/.agent/permissions.yaml`)

permissions.yaml 예시:
    mode: auto-edit            # suggest | auto-edit | full-auto
    allow_shell:               # 이 정규식들은 추가로 자동 승인
      - "^docker compose (ps|logs)"
    deny_shell:
      - "^git push"
    allow_paths:               # 이 glob 은 확인 없이 편집 허용
      - "src/**"
    deny_paths:                # 이 glob 은 편집/생성 차단 (기본 목록에 더해짐)
      - "config/prod/**"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_path

_USER_FILE = (
    user_config_path("gigachanie", appauthor=False, ensure_exists=False)
    / "permissions.yaml"
)
_PROJECT_REL = Path(".agent") / "permissions.yaml"

# 편집/생성을 기본 차단하는 경로 (민감정보 가드, F7)
DEFAULT_DENY_PATHS: list[str] = [
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa*",
    "**/id_ed25519*",
    "**/.ssh/**",
    "**/.aws/**",
    "**/.gnupg/**",
    "**/.npmrc",
    "**/.netrc",
    "**/.pypirc",
    ".git/**",
    "**/credentials*.json",
    "**/*secret*.y*ml",
]


@dataclass
class PermissionSettings:
    mode: str | None = None
    allow_shell: list[str] = field(default_factory=list)
    deny_shell: list[str] = field(default_factory=list)
    allow_paths: list[str] = field(default_factory=list)
    deny_paths: list[str] = field(default_factory=list)
    allow_domains: list[str] = field(default_factory=list)
    deny_domains: list[str] = field(default_factory=list)

    def effective_deny_paths(self) -> list[str]:
        return [*DEFAULT_DENY_PATHS, *self.deny_paths]


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text("utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data or {}


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        return [value]
    return []


def _project_file(root: Path) -> Path:
    return root / _PROJECT_REL


def load_permissions(root: Path) -> PermissionSettings:
    merged = PermissionSettings()
    for src in (_USER_FILE, _project_file(root)):
        data = _read(src)
        if not data:
            continue
        if data.get("mode"):
            merged.mode = str(data["mode"])
        merged.allow_shell += _list(data.get("allow_shell"))
        merged.deny_shell += _list(data.get("deny_shell"))
        merged.allow_paths += _list(data.get("allow_paths"))
        merged.deny_paths += _list(data.get("deny_paths"))
        merged.allow_domains += _list(data.get("allow_domains"))
        merged.deny_domains += _list(data.get("deny_domains"))
    return merged
