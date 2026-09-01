# 변경 이력

사용자 관점의 변경을 요약한다. 기능 추가·수정 시 이 파일과
[docs/기능명세.md](docs/기능명세.md), [docs/manual.html](docs/manual.html) 를 함께 갱신한다.

## [미출시]

### 문서
- HTML 사용 설명서 `docs/manual.html` 추가 (#26). 명령·옵션·도구·설정 레퍼런스.

### 추가
- `giga map` — 저장소 심볼 맵 (심볼 추출 + 참조 랭킹). `agent`/`chat` 은 컨텍스트에 자동 주입, `--no-map` 으로 끔 (#11)
- `giga memory add/list/show/search/rm` — 장기 메모리. `agent`/`chat` 은 목차를 컨텍스트에 주입하고 `read_memory`/`save_memory` 도구·`/remember`·`/memory` 로 접근 (#12)
- `giga doctor` — OS/CPU/RAM/GPU 감지 후 실행 가능한 오픈모델 추천 (#3)
- `giga model list / show / use / pull` — 모델 레지스트리 25종, 선택 시 가중치 자동 다운로드 (#3, #24)
- `giga ask` / `giga ping` — 단발성 질의, 백엔드 연결 확인 (#4)
- `giga agent` — 에이전트 루프 (읽기 도구 + `--write` 쓰기/셸 + `--web` 웹) (#5, #6, #20)
- `giga chat` — 대화형 REPL, 슬래시 명령 (#8)
- `giga init` — 리포 분석 후 `AGENTS.md` 초안 생성 (#10)
- 서빙 백엔드: Ollama, OpenAI 호환(llama.cpp/MLX/vLLM/호스팅) (#4)
- 도구: `list_dir` `read_file` `glob` `grep` `write_file` `apply_edit` `run_shell` `web_search` `web_fetch`
- SEARCH/REPLACE 편집 엔진 — 4단계 매칭 (#7)
- 승인 정책 — `suggest` / `auto-edit` / `full-auto` + 셸 allow/deny + network 게이트 (#6, #20)
- 프로젝트 컨텍스트 — `AGENTS.md`/`GEMINI.md`/`CLAUDE.md` 계층 로드, `@파일` 참조 (#10)

### 기반
- Python 3.11+, typer + rich CLI, pytest/ruff/mypy (#1)
- 기능 명세 체크리스트 (Claude Code / Gemini CLI / Codex CLI 벤치마킹) (#2)
