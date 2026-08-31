"""사용자 / 프로젝트 설정 로드·저장.

우선순위: 기본값 < 사용자 설정 < 프로젝트 설정 < 환경변수
(현재는 모델 선택 정보만 다룬다. 이후 확장.)
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_path

APP_NAME = "gigachanie"
_USER_CONFIG = user_config_path(APP_NAME, appauthor=False, ensure_exists=False) / "config.yaml"
_PROJECT_CONFIG_RELATIVE = Path(".agent") / "config.yaml"


@dataclass(frozen=True)
class Config:
    model_id: str | None = None
    backend: str = "ollama"  # ollama | openai_compat
    base_url: str | None = None  # openai_compat 용 (예: http://localhost:8000/v1)
    quant: str | None = None
    context: int | None = None

    def merged(self, **overrides: object) -> Config:
        clean = {k: v for k, v in overrides.items() if v is not None}
        return replace(self, **clean)  # type: ignore[arg-type]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text("utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data or {}


def user_config_file() -> Path:
    return _USER_CONFIG


def project_config_file(start: Path | None = None) -> Path | None:
    """작업 디렉터리에서 위로 올라가며 .agent/config.yaml 을 찾는다."""
    cur = (start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / _PROJECT_CONFIG_RELATIVE
        if candidate.is_file():
            return candidate
    return None


def _from_env() -> dict[str, object]:
    env_map = {
        "GIGA_MODEL": "model_id",
        "GIGA_BACKEND": "backend",
        "GIGA_BASE_URL": "base_url",
        "GIGA_QUANT": "quant",
    }
    out: dict[str, object] = {}
    for env_key, field_name in env_map.items():
        if env_key in os.environ and os.environ[env_key]:
            out[field_name] = os.environ[env_key]
    if "GIGA_CONTEXT" in os.environ:
        with contextlib.suppress(ValueError):
            out["context"] = int(os.environ["GIGA_CONTEXT"])
    return out


def _known_fields(data: dict[str, Any]) -> dict[str, Any]:
    valid = set(Config.__dataclass_fields__)
    return {k: v for k, v in data.items() if k in valid}


def load_config(start: Path | None = None) -> Config:
    cfg = Config()
    cfg = cfg.merged(**_known_fields(_read_yaml(_USER_CONFIG)))
    proj = project_config_file(start)
    if proj is not None:
        cfg = cfg.merged(**_known_fields(_read_yaml(proj)))
    cfg = cfg.merged(**_from_env())
    return cfg


def save_user_config(cfg: Config) -> Path:
    _USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in asdict(cfg).items() if v is not None}
    _USER_CONFIG.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    return _USER_CONFIG
