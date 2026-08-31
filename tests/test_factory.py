"""백엔드 팩토리 테스트."""

import pytest

from gigachanie.config import Config
from gigachanie.serving.base import BackendError
from gigachanie.serving.factory import build_backend
from gigachanie.serving.ollama import OllamaBackend
from gigachanie.serving.openai_compat import OpenAICompatBackend


def test_모델미선택시_오류() -> None:
    with pytest.raises(BackendError):
        build_backend(Config())


def test_ollama_백엔드_생성_및_태그_해석() -> None:
    cfg = Config(model_id="qwen2.5-coder-7b-instruct", backend="ollama", context=8192)
    be = build_backend(cfg)
    assert isinstance(be, OllamaBackend)
    assert be.model == "qwen2.5-coder:7b"  # 레지스트리의 ollama_tag 로 치환
    assert be.tool_mode == "native"
    assert be.num_ctx == 8192


def test_openai_compat_백엔드_base_url_필수() -> None:
    cfg = Config(model_id="qwen2.5-coder-7b-instruct", backend="openai_compat")
    with pytest.raises(BackendError):
        build_backend(cfg)


def test_openai_compat_백엔드_생성() -> None:
    cfg = Config(
        model_id="deepseek-coder-v2-lite-instruct",
        backend="openai_compat",
        base_url="http://localhost:8000/v1",
    )
    be = build_backend(cfg)
    assert isinstance(be, OpenAICompatBackend)
    assert be.tool_mode == "prompt"  # 레지스트리 값


def test_알수없는_백엔드() -> None:
    cfg = Config(model_id="qwen2.5-coder-7b-instruct", backend="triton")
    with pytest.raises(BackendError):
        build_backend(cfg)
