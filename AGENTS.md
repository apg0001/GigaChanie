# GigaChanie

> GigaChanie 에이전트가 매 세션 이 파일을 읽습니다. (`giga init` 초안을 다듬은 것)

## 프로젝트 개요

- 오픈 웨이트 LLM(Qwen, Llama, DeepSeek 등)으로 동작하는 터미널 코딩 에이전트.
- Cursor / Claude Code 처럼 프로젝트를 이해하고 파일을 편집하며 명령을 실행한다.
- 주요 언어: Python 3.11+ (CLI). VS Code 확장은 `extension/` 에 TypeScript.
- 저장소: https://github.com/apg0001/GigaChanie.git
- 상태: CLI(31개 명령) + `giga serve` 브리지 + VS Code 확장 기능 완성. 기능명세 76개 중 75개 완료.
- 명령: setup·doctor·ping·ask·agent·plan·prompts·chat·init·map·eval·undo·ps·kill·policy·
  route·ensemble·divide·spec·runlog·serve·review·render·commit·pr + memory/mcp/model/sessions/self/ext 서브앱

## 빌드 · 실행

- 설치: `python -m pip install -e ".[dev]"`
- 실행: `giga --help` (또는 `python -m gigachanie`)

## 테스트

- `python -m pytest` — 모든 변경은 테스트를 통과해야 한다.
- 백엔드 테스트는 `httpx.MockTransport` / `ScriptedBackend`(tests/conftest.py) 로 실제 서버 없이 돈다.

## 린트 · 타입체크

- `ruff check .` (line-length 100)
- `mypy` (strict). 새 코드는 타입 힌트를 완전히 붙인다.

## 디렉터리

- `src/gigachanie/commands/` — CLI 하위 명령 (cli.py 에서 등록만)
- `src/gigachanie/providers/` — 하드웨어 감지, 모델 레지스트리, 추천
- `src/gigachanie/serving/` — 백엔드 어댑터 (ollama, openai_compat), 툴콜 파싱
- `src/gigachanie/loop/` — 에이전트 루프, 도구, 승인 정책, 편집 엔진, hunk 선택, 샌드박스, 관측
- `src/gigachanie/context/` — 프로젝트 컨텍스트, @참조 확장, repo map, 메모리, 재사용 프롬프트, 예산
- `src/gigachanie/orchestra/` — 라우터, 초안-검수 파이프라인, 앙상블, 작업 분할, 스펙 협업
- `src/gigachanie/serve/` — `giga serve` stdio JSON-RPC 브리지 (VS Code 확장의 백엔드)
- `extension/` — VS Code 확장 (별도 npm 프로젝트, `npm run compile`)
- `docs/` — 기능명세(체크리스트), 아키텍처, 로드맵, 이슈목록, CI레시피, manual.html(사용 설명서)

## 코드 컨벤션

- 모든 주석·docstring·로그·커밋·문서는 **한국어**.
- 루프/도구/백엔드는 async. CLI 에서는 `serving.base.run_sync` 로 감싼다.
- 도구 오류는 예외로 던지지 말고 `ToolResult.error` 로 모델에 피드백한다.
- 하위 명령은 `commands/<name>.py` 에 구현하고 `cli.py` 에서 등록.

## git 규칙 (CONTRIBUTING.md 참고)

- 작업 단위로 잘게 커밋·푸시. 이슈별 브랜치에서 작업.
- 브랜치: `타입/#이슈번호-설명`, 커밋 제목: `[타입] 한국어 설명`.
- 커밋 본문은 육하원칙으로 자세히.
- 이슈 완료 시 `docs/기능명세.md` 체크박스와 `docs/이슈목록.md` 상태를 갱신한다.
- 새 명령·옵션·도구를 추가하면 `docs/manual.html` 과 `CHANGELOG.md` 도 같은 커밋에서 갱신한다.

## 주의사항

- `src/gigachanie/providers/model_registry.yaml` 의 layers/kv_heads/head_dim 은
  `giga doctor` 의 KV 캐시 계산에 쓰이므로 실제 config 값과 맞춰야 한다.
- `gh` CLI 미설치 환경. GitHub 이슈는 `docs/이슈목록.md` 로 관리.
