# 변경 이력

사용자 관점의 변경을 요약한다. 기능 추가·수정 시 이 파일과
[docs/기능명세.md](docs/기능명세.md), [docs/manual.html](docs/manual.html) 를 함께 갱신한다.

## [미출시]

### 문서
- HTML 사용 설명서 `docs/manual.html` 추가 (#26). 명령·옵션·도구·설정 레퍼런스.
- `.github/workflows/ci.yml`(ruff·mypy·pytest 매트릭스 + 확장 컴파일) + `docs/CI레시피.md`(giga review / agent --json / eval 을 CI 잡으로 쓰는 워크플로 예제) 추가 (#35)

### 수정
- 네이티브 툴콜에 실패하고 본문에 `{"name": "...", "arguments": {...}}` JSON 을 그대로 뱉는 모델(qwen2.5-coder:7b 등) 대응 — 등록된 도구 이름과 일치하면 실제 도구 호출로 복구. 임의 언어 코드펜스(```sh, ```python …), 한 블록에 여러 개, 펜스 없는 본문, `parameters`/`input` 키, `{"tool_calls": [...]}` 래핑 모두 인식. 실사용 테스트에서 qwen 이 파일 생성 툴콜을 전부 ```sh JSON 으로 뱉어 아무것도 안 만들던 문제를 잡음 (#49, #54)
- `giga chat` / `giga agent` 에서 스트리밍된 답변이 하단에 한 번 더 반복 출력되던 문제 수정 — 이벤트 프린터가 이미 답변을 보여줬으면 최종 블록을 생략 (#49)
- Windows에서 Ollama가 표준 설치 경로에 있지만 현재 프로세스 `PATH`에 없을 때도
  설치·실행 상태를 인식하고, winget의 "적용 가능한 업그레이드 없음"을 실패로
  오표시하지 않도록 수정 (#29)
- Pandoc으로 HTML을 렌더링할 때 완전한 문서(`<!doctype html>`)가 생성되도록 수정 (#30)
- 시스템 프롬프트: 편집 도구가 주어졌을 때 소형 모델이 "저는 AI라 직접 수정할 수 없습니다"라고 답하는 경향을 억제. 도구로 실제 변경을 수행하고, 편집 도구가 없을 때만 `-w` 안내를 하도록 지시 추가
- `giga serve` / `giga mcp serve`: Windows 에서 stdout 이 cp949 라 한국어가 섞인 JSON-RPC 응답(오류 메시지 등)을 상대가 UTF-8 로 못 읽던 문제 수정 (진입점에서 stdin/stdout 을 UTF-8·LF 로 고정, `_stdio.py`)
- Windows 콘솔(cp949)에서 유니코드 기호(✔ ✗ → 등) 출력 시 `UnicodeEncodeError` 로 명령이 죽던 문제 수정 — `ui.py` 가 import 시 stdout/stderr 를 UTF-8 로 재설정
- 반복 가드(같은 도구 호출 N회 초과)로 루프를 멈출 때, 아직 응답하지 않은 `tool_calls` 를 가진 assistant 메시지가 그대로 남아 메시지 짝이 깨지던 문제 수정. 세션 저장 후 `--resume` 하거나 `giga serve` 로 대화를 이어가면 백엔드가 "tool 응답 없는 tool_calls" 로 거부했음. 이제 중단 시 남은 호출을 모두 합성 tool 결과로 답해 둔다 (#58)
- 세션 자동 압축(요약 생성) 호출에 쓴 토큰이 사용량 누계에 빠져 `--budget` 조기 종료 판정과 `agent --json` / `/cost` 토큰 수치가 실제보다 작게 나오던 문제 수정 — `compact()` 가 요약 호출 토큰을 반환하고 에이전트가 누계에 더함 (#58)
- 네이티브 툴콜에 실패하고 본문 JSON(``` 펜스 포함)으로 도구 호출을 뱉는 모델을 스트리밍으로 쓸 때, 원시 JSON(`{"name": "write_file", …}`)이 화면에 그대로 흘러가던 문제 수정. 스트림 게이트가 도구 호출 마커 이후 구간을 실시간 표시에서 가리고, 파싱이 끝나면 실제 답변 텍스트만 채운다. 마커가 오탐이면(도구 호출 아님) 종료 시 보류분을 복구 출력 (#59)
- `giga review` / `agent --review`: 검토 모델이 "문제 없음"에 마침표·사족(`문제 없음.`, `No issues.`, `문제 없음\n검토를 마쳤습니다`)을 붙이면 문제가 있는 것으로 잘못 판정해 불필요한 재수정을 돌리던 문제 수정 — 첫 줄이 "문제 없음"류이고 뒤에 지적 불릿이 없으면 통과로 본다 (#59)
- `giga serve` 가 프롬프트를 처리해도 대화를 디스크에 저장하지 않아, VS Code 확장의 "이전 세션 이어가기"가 확장으로 만든 대화는 목록에 못 띄우고 재개도 못 하던 문제 수정. 이제 프롬프트마다·세션 종료 시 `.agent/sessions/` 에 저장하고 `session/new` 응답에 `storeId` 를 실어 준다 (#60)
- 에이전트 실행이 이벤트 콜백에서 던진 예외(에디터 브리지의 취소 등)로 중단되면 체크포인트 턴이 안 닫혀, 그때까지 수정한 파일을 `giga undo` 로 되돌릴 수 없고 다음 턴 스냅샷과 섞이던 문제 수정 — `run()` 이 `try/finally` 로 항상 턴을 닫는다 (#61)
- 이미지(`@사진.png`)를 첨부한 대화를 저장했다가 `--resume` 하면 첨부가 사라지던 문제 수정 — 세션 직렬화가 메시지의 `images` 필드를 함께 저장·복원 (#62)

### 추가
- VS Code 확장 UX 개편 — (1) 왼쪽 사이드바 뷰 **또는** 에디터 탭으로 열 수 있음(`GigaChanie: 채팅 탭 열기` 명령 / `Ctrl+Alt+G`, 탭은 다른 편집기 그룹으로 끌어 오른쪽 분할 가능). 두 화면이 같은 대화·세션을 공유. (2) 채팅 헤더에서 **모델·승인 모드·write·web 을 클릭 한 번으로 전환** — 설정 JSON 을 안 열어도 됨. 모델 버튼은 설치 여부·장비 적합도가 표시된 목록을 띄우고 "이 세션만" / "기본값으로 저장" 선택 가능. `giga serve` 에 `models/list`·`models/use` 메서드와 `session/new {model}` 오버라이드 추가 (#64)
- `run_shell` 출력 실시간 스트리밍 — 명령이 끝나기를 기다리지 않고 출력을 나오는 대로 보여준다. `giga agent`/`giga chat` 은 콘솔에 즉시 흘려 쓰고(결과에는 종료줄만), `giga serve` 는 `session/event {kind:"tool_output"}` 알림. `pytest`·빌드처럼 오래 걸리는 명령의 진행 상황을 볼 수 있다. 타임아웃돼도 그때까지 출력은 결과에 남는다. Windows 자식 프로세스는 콘솔·`PYTHONUTF8` 을 UTF-8 로 맞춰 한국어 출력이 안 깨진다 (#63)
- `giga plan "작업"` — 계획 모드. 읽기 도구만으로 코드베이스를 조사해 번호 매긴 실행 계획 + "확인 필요"·"위험"을 출력하고 파일은 건드리지 않음. `-x` 를 주면 계획 확인 후 곧바로 `giga agent -w --mode auto-edit` 로 실행 (#32)
- `update_tasks` 도구 — 에이전트가 3단계 이상 작업을 체크리스트로 분해하고 단계마다 진행 상태(pending/active/done)를 갱신. CLI 와 VS Code 확장이 ✔/▶/○ 로 렌더. 목록은 세션 범위(파일 미기록) (#33)
- 커스텀 프롬프트 — `.agent/prompts/<이름>.md`(전역 `~/.config/gigachanie/prompts/` 도) 재사용 지시문을 `giga agent -p <이름>` / `giga chat -p <이름>`(반복 가능)으로 시스템 프롬프트에 얹음. `giga prompts` 로 목록·본문. 커스텀 슬래시 명령(한 번 실행)과 달리 세션 내내 유지 (#36)
- 사고 모드 — `giga agent` / `giga chat` 의 `--think`(단계적 추론 유도) / `--think-hard`(여러 접근 비교·반례 탐색). 시스템 프롬프트 숙고 지시 + 백엔드 네이티브 reasoning 파라미터(Ollama `think`, OpenAI 호환 `reasoning_effort`)를 low/high 로 전달. 미지원 서버는 무시 (#37, #44)
- 접근성 — 환경변수 `NO_COLOR`(표준) / `GIGA_NO_COLOR` 로 색·스타일 제거, `GIGA_PLAIN` 으로 하이라이트·이모지까지 끄고 대화형 선택을 번호 입력으로. 모든 명령이 공용 콘솔을 쓰도록 통일 (#38)
- `run_subagent` 도구 — 하위 작업을 독립 컨텍스트(부모 대화 미상속)의 에이전트에 위임. 조사·요약처럼 중간 산출물이 많은 작업을 떼어내 부모 컨텍스트를 아낌. 깊이 제한 2, 부모가 쓰기 모드일 때만 편집 허용 (#39)
- `giga ensemble "질문" -m A -m B [-j 판정]` — N개 모델을 같은 질문에 병렬로 돌리고(도구 미사용) 판정 모델이 하나로 종합. `-m` 은 모델 ID 또는 `orchestra.yaml` 슬롯 (#40)
- `giga divide "목표" [-w]` — 플래너 모델이 목표를 3~6개 하위 작업으로 나누고, 각 하위 작업을 독립된 `giga agent` 실행으로 순차 처리. `--dry-run` 으로 분할만 미리보기 (#41)
- `giga spec "요구사항" [-d 초안] [-r 검증] [-o 파일]` — 소형 모델이 구현 계획 초안을 쓰고 대형 모델이 오류·엣지케이스를 지적한 뒤 최종본을 다시 씀 (#42)
- `giga ext install/list/remove` — 확장 패키지. `giga-ext.yaml` + `commands/*.md` + `prompts/*.md` 디렉터리를 `.agent/` 로 복사·기록. MCP·훅은 위험하므로 자동 병합 안 함 (#43)
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
- MCP 클라이언트 — `.mcp.json`(Claude Code 호환)에 정의한 MCP 서버(stdio)의 도구를 `giga agent --mcp` 로 에이전트에 노출. `giga mcp list`(설정)·`giga mcp check`(연결·도구 확인). 외부 SDK 의존 없음 (#18)
- 대화 세션 저장/재개 — `giga chat` 이 턴마다 `.agent/sessions/` 에 저장. `giga chat --continue`(최근 이어가기) / `--resume <id>`, `giga sessions list/rm` (#21)
- git 도우미 — `giga commit`(AGENTS.md/CONTRIBUTING.md 의 git 규칙을 반영해 모델이 커밋 메시지 생성, `-a`/`-m`/`--push`), `giga pr`(커밋 범위로 PR 제목/본문 초안, `gh` 있으면 `--create`) (#22)
- 커스텀 슬래시 명령 — `.agent/commands/<이름>.md` 를 `chat` 에서 `/이름 인자` 로 실행 (`$ARGUMENTS`·`{{args}}`·`$1..` 치환). `/commands` 로 목록 (#19)
- 훅 — `.agent/hooks.yaml` 로 `pre_tool`(종료코드≠0 이면 도구 차단)·`post_tool`·`session_start`·`stop` 에서 셸 명령 실행 (#19)
- `giga agent --json` — 결과를 JSON(ok·final_text·stop_reason·steps·tokens·changed_files)으로 출력, 진행 소음 억제. CI 용 (#21b)
- 토큰 사용량 — `chat` 이 매 턴 후 토큰(이번/누적) 표시, `/cost` 로 세션 누적 확인 (#21b)
- 멀티모달 입력 — 프롬프트의 `@사진.png` 는 이미지로(비전 모델), `@문서.pdf` 는 텍스트 추출(`pip install gigachanie[pdf]`)로 첨부 (#20b)
- 문서 렌더링 — `giga render in.md -o deck.pptx`(또는 .docx/.html). 에이전트도 `render_document` 도구로 슬라이드·문서 생성. pandoc 있으면 우선 사용, 없으면 python-pptx/python-docx/markdown 폴백(`pip install "gigachanie[docs]"`) (#30)
- 셸 샌드박스 — `giga agent --sandbox`: Linux=bubblewrap/firejail, macOS=sandbox-exec 로 `run_shell` 격리(쓰기를 작업 루트로 제한). `--no-network` 로 망 차단. Windows 는 미지원(승인 정책에 의존) (#15)
- 실행 로그 — `agent`/`chat` 실행마다 `.agent/logs/runs.jsonl` 에 한 줄(시각·모델·성공·스텝·토큰·도구별 호출수·편집실패·변경파일·소요초). `giga runlog`(표), `giga runlog --stats`(통과율·합계) 로 조회. 프롬프트/모델 바꿔가며 추이 확인용 (#22b)
- 자기 점검·업데이트 — `giga self info`(설치 방식·버전·PyPI 최신 여부), `giga self check`(파이썬·의존성·임포트 진단), `giga self update`(editable=git pull / pipx=upgrade / pip=`-U`, `--dry-run`·`--check`), `giga self fix "문제"`(에이전트를 GigaChanie 자기 저장소에 `--write --web` 로 돌려 웹·코드 조사 후 수정하고 pytest 로 검증; 소스 설치에서만) (#31)
- `giga mcp serve` — GigaChanie 도구(read_file·grep·update_tasks 등)를 stdio MCP(JSON-RPC 2.0)로 Claude Desktop 같은 외부 에이전트에 제공. 기본 읽기 전용, `-w` 로 쓰기(승인 없이), `--web` 로 웹 도구. `.mcp.json` 에 `{"mcpServers":{"gigachanie":{"command":"giga","args":["mcp","serve"]}}}` 로 등록 (#34)
- `giga serve` — 에디터/GUI 용 stdio JSON-RPC 2.0 브리지. `session/new`·`session/info`·`session/prompt`(이벤트 스트리밍)·`session/cancel`·`session/approve`·`session/answer`·`session/close`·`shutdown`. 알림 `session/event`·`session/approval`·`session/ask`. 승인·`ask_user` 질문을 큐로 왕복, 취소 지원, `session_start`/`stop` 훅 발화. stdout 은 JSON-RPC 만, 로그는 stderr (#23)
- VS Code 확장 (`extension/`, TypeScript) — 활동표시줄 GigaChanie 채팅 뷰, 에이전트 이벤트 실시간 스트리밍, `suggest` 모드에서 뷰 내 허용/거부 승인, `ask_user` 는 QuickPick·입력창으로, 상태줄 위젯(모델·모드·실행중), 답변의 변경 파일 클릭 시 에디터에서 열기, 명령(새 세션·작업 실행·취소·재시작)·설정(`gigachanie.command/mode/write/web/maxSteps`). `giga serve` 를 자식 프로세스로 사용. `npm run package` 로 `.vsix` 배포 파일 생성 가능 (#23)
- 저장소 루트에 `LICENSE`(MIT) 추가 — `pyproject.toml`·확장 매니페스트가 선언하던 라이선스의 실제 파일

### 개선
- 에이전트 루프: 모델이 도구를 호출하지 않고 "~하겠습니다" 같은 계획·의도만 답하거나 본문에 코드블록만 써 놓으면, 바로 종료하지 않고 최대 2회까지 "실제로 도구를 호출하라"고 다시 요청 (약한 모델 대응). 읽기 전용 세션에선 넛지 안 함 (#55)
- **시스템 프롬프트를 절반 이하로 축약** (#56). 실측 결과 장황한 한국어 프롬프트에서 qwen2.5-coder:7b 의 도구 호출률이 0/8 이었는데(모델이 도구 대신 "계획"을 본문에 씀), 짧고 명령형으로 바꾸니 8/8 로 회복. 소형 모델 실사용성이 크게 개선됨
- 에이전트 루프: 모델이 `<tool_response>` 같은 태그로 **도구 출력을 지어내면** 감지해 "그건 실제 도구 출력이 아니다, 지금 도구를 호출하라"고 재요청 (#57, qwen 이 자주 하는 환각)
- `apply_edit` 에 `replace_all` 인자 추가 — search 가 여러 곳과 일치할 때 전부 바꾼다. 다중 매칭 오류 메시지도 이 옵션을 안내 (#57)
- `grep` 도구: `rg`(ripgrep)가 있으면 그걸로 검색(빠름), 없으면 순수 파이썬 폴백 (#45, B5)
- `giga chat` `/diff` 슬래시 명령 — 작업 트리 변경을 rich diff 로 (`--stat` 또는 git 인자 전달) (#45, H5)
- `giga agent --sandbox`: `run_background` 로 띄우는 프로세스도 `run_shell` 과 동일하게 격리 (#45, F4)
- `giga agent --budget N` — 누적 토큰이 N 을 넘으면 중단(`stop_reason=budget`). Ctrl-C 로 중단하면 부분 결과를 깔끔히 반환(`stop_reason=cancelled`) (#46, A2)
- `@경로` 참조가 존재하지 않는 파일이면 경고, 디렉터리면 파일 지정 안내. 확장자·경로 없는 평범한 단어는 무시 (#46, C10)
- 네트워크 정책 — `permissions.yaml` 의 `allow_domains` / `deny_domains` (하위 도메인 매칭, deny 우선, allow 목록 있으면 화이트리스트). `web_fetch` 가 호스트 검사 (#47, F5)
- 컨텍스트 예산 — 모델 컨텍스트 창의 22%를 프로젝트 컨텍스트·repo map·메모리 목차에 4:4:2 로 배분(최소치 보장), 초과분은 잘라냄 (#47, C8)
- 모델 슬롯 언로드 — `giga ensemble`/`divide`/`spec` 이 각 모델 사용 후 Ollama 에서 언로드(keep_alive:0)해 다음 모델을 위한 VRAM 확보 (#48, E6)
- `giga chat` 하단 상태줄 — 모델·모드·쓰기·웹·턴·누적 토큰 상시 표시 (`GIGA_PLAIN` 이면 생략) (#48, H7)
- OpenTelemetry — `GIGA_OTEL=1` + `pip install gigachanie[otel]` 시 agent run 당 span 을 OTLP 로 내보냄. 없으면 no-op (#48, I4)
- `giga eval` 태스크셋 3 → 15종(이름변경·타입힌트·죽은코드·docstring·함수추출·설정·CLI·상수·테스트작성·파일핸들·빈리스트·기하). 판정 `file_absent_text` 추가 (#50, J2)
- `giga eval` 회귀 게이트 — 같은 모델의 통과율을 `.agent/eval-history.jsonl` 에 기록, 직전 대비 하락하면 종료코드 2 (`--no-history` 로 끔) (#50, J4)
- `giga chat` 자동완성 — `/` 입력 시 슬래시 명령(+커스텀), `@` 입력 시 워크스페이스 파일·디렉터리 (#50)
- VS Code 확장 — 답변에 나온 변경 파일 옆 `(diff)` 로 HEAD 대비 변경을 diff 뷰로, 입력창에서 `@` 뒤 파일명 자동완성(↑↓/Tab) (#51, I5)
- 편집 승인에 `[h] hunk 선택` 추가 — diff 를 변경 덩어리로 쪼개 각각 y/n, 선택된 것만 파일에 적용 (#52, F3)
- `giga chat` 프롬프트에서 Ctrl-C 를 두 번(2초 내) 눌러야 종료. 한 번이면 안내만 (실수로 세션이 날아가지 않도록) (#52)
- `giga chat` 시작 시 이어갈 수 있는 이전 세션이 있으면 안내 (`-c` 로 이어감) (#53)
- `giga serve` `session/new` 가 `prompts`·`think`/`thinkHard`·`budget`·`resume`(세션 이어가기) 지원, 컨텍스트 예산·서브에이전트·도메인 정책도 CLI 와 동일하게 적용. `session/history` 로 저장된 세션 목록 (#53)
- VS Code 확장 — "이전 세션 이어가기" 명령, 설정 `gigachanie.prompts`·`gigachanie.think` 추가 (#53)

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
