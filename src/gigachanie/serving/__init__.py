"""모델 서빙 백엔드.

오픈모델을 OpenAI 호환 인터페이스로 감싼다. 에이전트 루프는 `Backend` 프로토콜만 의존한다.
"""

from gigachanie.serving import ollama_setup
from gigachanie.serving.base import (
    Backend,
    ChatResponse,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from gigachanie.serving.factory import build_backend

__all__ = [
    "Backend",
    "ChatResponse",
    "Message",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "build_backend",
    "ollama_setup",
]
