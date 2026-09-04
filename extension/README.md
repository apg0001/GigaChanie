# GigaChanie for VS Code

오픈 웨이트 LLM 코딩 에이전트 [GigaChanie](https://github.com/apg0001/GigaChanie) 를
VS Code 에서 사용하는 확장입니다.
CLI(`giga`)를 `giga serve` stdio JSON-RPC 브리지로 띄워 통신합니다.

## 설치

- 개발/사내 배포: `npm run package` → `gigachanie-vscode-<버전>.vsix` 생성 →
  `code --install-extension gigachanie-vscode-0.0.1.vsix` (또는 VS Code 확장 탭 → … → "VSIX에서 설치").
- Marketplace 공개 배포: `vsce` 퍼블리셔 계정을 만들고 `package.json` 의 `publisher` 를
  실제 퍼블리셔 ID 로 바꾼 뒤 `npm run publish` (Azure DevOps PAT 필요).

## 요구사항

- `giga` CLI 가 설치되어 PATH 에 있어야 합니다 (`pip install -e .` 등).
  경로가 다르면 설정 `gigachanie.command` 에 절대경로를 지정하세요.
- 모델 백엔드(Ollama 등)가 준비되어 있어야 합니다 (`giga doctor`, `giga model use`).

## 개발

```bash
cd extension
npm install
npm run compile      # 또는 npm run watch
```

VS Code 에서 이 폴더를 열고 F5 (Extension Development Host) 로 실행합니다.

## 기능 (v0.0.1)

- **사이드바 뷰 또는 에디터 탭** — 활동 표시줄의 **GigaChanie** 뷰, 또는
  `GigaChanie: 채팅 탭 열기`(`Ctrl+Alt+G` / macOS `Cmd+Alt+G`)로 에디터 탭을 열어
  다른 편집기 그룹으로 끌어 오른쪽에 둘 수 있습니다. 두 화면은 같은 대화·세션을 공유합니다.
- **채팅 헤더에서 즉시 전환** — 모델(설치 여부·장비 적합도 표시, "이 세션만" / "기본값으로 저장"),
  승인 모드(suggest/auto-edit/full-auto), `write`, `web`. 설정 JSON 을 열 필요 없음.
- 에이전트 이벤트(도구 호출/결과/최종 답변) 실시간 스트리밍, 셸 출력은 나오는 대로 표시
- `suggest` 모드에서 쓰기/셸 실행 시 뷰 안에서 **허용/거부** 승인
- `ask_user` 명확화 질문은 QuickPick(+직접 입력)으로 응답
- 상태 표시줄에 모델·승인 모드·실행 상태 표시
- 답변에 나온 변경 파일을 클릭하면 에디터에서 열림, `(diff)` 로 HEAD 대비 변경 확인
- 입력창에서 `@` 뒤에 파일명을 치면 워크스페이스 파일 자동완성 (↑↓/Tab)
- `GigaChanie: 이전 세션 이어가기` — 저장된 대화를 골라 이어감 (확장/CLI 대화 모두)
- 명령: `채팅 탭 열기`, `새 세션`, `작업 실행…`, `모델 선택`, `실행 취소`,
  `이전 세션 이어가기`, `브리지 재시작`
- 설정: `gigachanie.command`, `gigachanie.model`, `gigachanie.mode`, `gigachanie.write`,
  `gigachanie.web`, `gigachanie.maxSteps`, `gigachanie.prompts`, `gigachanie.think`

## 프로토콜

`giga serve` 와 주고받는 JSON-RPC 2.0 메서드:

| 메서드 | 방향 | 설명 |
| --- | --- | --- |
| `initialize` | → | 버전/프로토콜/cwd |
| `session/new` | → | `{root, write, web, mode, model?, maxSteps, prompts, think, thinkHard, budget, resume}` → `{sessionId, storeId, model, tools, mode, web, writable, resumedTurns}` (대화는 `storeId` 로 자동 저장·재개, `model` 로 세션별 모델 지정) |
| `session/info` | → | 현재 모델·모드·도구·실행 여부·턴 수 |
| `session/history` | → | 저장된 세션 목록 (id·제목·모델·턴) |
| `models/list` | → | `{current, backend, models:[{id, display, params, installed, fit, …}]}` |
| `models/use` | → | `{model}` — 사용자 설정에 기본 모델로 저장 |
| `session/prompt` | → | `{sessionId, text}` → `{ok, finalText, stopReason, steps, tokens, changedFiles}` |
| `session/cancel` | → | 실행 중인 프롬프트 취소 |
| `session/approve` | → | `{sessionId, requestId, decision}` (allow/deny/always) |
| `session/answer` | → | `{sessionId, requestId, answer}` — `ask_user` 질문 응답 |
| `session/close` | → | 세션 종료 |
| `shutdown` | → | 브리지 종료 |
| `session/event` | ← | AgentEvent 스트림 `{kind, text, toolName, isError, step}` (`kind` 에 `tool_output` = 셸 등의 실시간 부분 출력) |
| `session/approval` | ← | `{requestId, kind, summary, detail, path}` |
| `session/ask` | ← | `{requestId, question, options, allowCustom}` |
