# 변경 이력

사용자 관점의 변경을 요약한다. 기능 추가·수정 시 이 파일과
[docs/기능명세.md](docs/기능명세.md), [docs/manual.html](docs/manual.html) 를 함께 갱신한다.

## [미출시]

### 문서
- HTML 사용 설명서 `docs/manual.html` 추가 (#26). 명령·옵션·도구·설정 레퍼런스.

### 추가
- `giga map` — 저장소 심볼 맵 (심볼 추출 + 참조 랭킹). `agent`/`chat` 은 컨텍스트에 자동 주입, `--no-map` 으로 끔 (#11)
- `giga memory add/list/show/search/rm` — 장기 메모리. `agent`/`chat` 은 목차를 컨텍스트에 주입하고 `read_memory`/`save_memory` 도구·`/remember`·`/memory` 로 접근 (#12)
- 세션 대화 자동 압축 — 토큰 추정치가 임계값(컨텍스트의 70%) 초과 시 오래된 메시지를 요약으로 치환. `--compact-at`, `/compact` (#12b)
- `giga eval` — 태스크셋으로 에이전트 통과율·편집실패·스텝/토큰 측정. 내장 태스크 3종, `--task`·`--json`, 전부 통과 시에만 종료코드 0 (#14)
- `giga undo` — 에이전트가 마지막 턴에 수정한 파일을 그 이전 상태로 복원. `--list`, `/undo`, `--no-checkpoint` (#13)
- 백그라운드 프로세스 — `run_background`/`tail_logs`/`wait_for_log`/`stop_process`/`list_processes` 도구, `giga ps`·`giga kill`·`/ps`. dev 서버 띄우고 로그 관찰 흐름 지원 (#25)
- 권한 규칙 — `permissions.yaml`(사용자 < 프로젝트) 로 승인 모드·셸 정규식·편집 경로 glob 설정. 기본 보호 경로(.env, *.pem, .ssh 등) 편집 차단 + 민감 파일 읽기 경고. `giga policy` (#9)

- 대화형 선택 UI — `giga model use`(인자 없이 실행 시 화살표 선택), `giga doctor --use`(진단→선택→설정), 승인 프롬프트 3지선다([y]/[n]/[a]항상 허용→permissions.yaml 자동 기록). 비 TTY 는 번호 입력 폴백 (#27)
- `ask_user` 도구 — 에이전트가 사용자만 결정할 수 있는 모호한 지점에서 추측 대신 선택지/자유입력을 요청. 비대화 세션은 "가정하고 진행" 안내 (#28)
- 멀티 모델 라우터 — `.agent/orchestra.yaml` 로 모델 슬롯(fast/heavy 등)과 규칙을 정의하면 첫 지시문을 분류해 세션 모델을 자동 선택. `giga route "작업"` 으로 결정 미리보기 (#16)
- Ollama 자동 설치 — `giga model use` 에서 Ollama 가 없으면 "설치할까요?" 확인 후 winget(Win)/brew(mac)/install.sh(Linux)로 설치하고 데몬을 기다림. `giga setup` 은 설치+모델 설정을 한 번에 안내 (#29)
- 초안→검수 파이프라인 — `giga review`(git diff 를 검토 모델에게 리뷰), `giga agent --review`(작업 후 자동 리뷰)·`--review-fix`(지적 1회 반영). orchestra.yaml 의 `pipeline.review` 슬롯 사용 (#17)

### 변경
- `agent`/`chat` 의 `--mode` 기본값이 `suggest` 고정 → permissions.yaml 의 `mode` 값 (없으면 suggest)
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
