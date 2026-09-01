# GigaChanie

오픈 웨이트 LLM(Qwen, Llama, DeepSeek, GLM, Mistral 등)으로 동작하는 **코딩 에이전트**입니다.
Cursor / Claude Code 처럼 프로젝트를 이해하고, 파일을 편집하고, 명령을 실행하며 작업을 진행합니다.
상용 API에 의존하지 않고 로컬(Ollama / llama.cpp / MLX) 또는 호스팅 오픈모델 위에서 돌아가는 것을 목표로 합니다.

## 특징 (목표)

- **로컬 우선**: Ollama · llama.cpp · MLX 등 OpenAI 호환 백엔드에 연결
- **하드웨어 인식 모델 추천** (`giga doctor`): OS/CPU/RAM/GPU를 감지해 실행 가능한 모델을 표로 제시, 사용자가 선택
- **넓은 모델 후보군**: Qwen · Llama · DeepSeek · GLM · Mistral(Codestral/Devstral) · Gemma · Phi · StarCoder2 등
- **멀티 모델 오케스트레이션**: 라우팅 / 앙상블 투표 / 작업 분할 / 초안-검수 파이프라인
- **메모리 하네스**: 프로젝트 컨텍스트(AGENTS.md) + 장기 메모리 + 세션 컨텍스트 압축
- **repo map**: tree-sitter 심볼 추출 + 그래프 랭킹으로 코드베이스를 압축해 컨텍스트에 주입
- **안정적 편집**: SEARCH/REPLACE 블록 파싱 방식 (소형 모델 신뢰성 확보)
- **평가 하네스**: 회귀 테스트용 태스크셋으로 프롬프트/모델 변경 영향 측정

## 진행 순서

1. **CLI 완성** (현재 단계)
2. GUI — VS Code 확장 또는 독립 데스크톱 앱

## 개발

```bash
python -m pip install -e ".[dev]"
giga --help
pytest
```

## 문서

- [사용 설명서 (HTML)](docs/manual.html) — 명령·도구·설정 레퍼런스
- [변경 이력](CHANGELOG.md)
- [기능 명세 · 진행 체크리스트](docs/기능명세.md)
- [아키텍처](docs/아키텍처.md)
- [로드맵](docs/로드맵.md)
- [모델 오케스트레이션 설계](docs/오케스트레이션.md)
- [이슈 목록](docs/이슈목록.md)
- [기여 가이드 / git 규칙](CONTRIBUTING.md)
