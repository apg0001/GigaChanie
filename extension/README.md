# GigaChanie for VS Code

오픈 웨이트 LLM 코딩 에이전트 [GigaChanie](../) 를 VS Code 에서 사용하는 확장입니다.
CLI(`giga`)를 `giga serve` stdio JSON-RPC 브리지로 띄워 통신합니다.

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

- 활동 표시줄의 **GigaChanie** 뷰에서 대화형으로 에이전트 실행
- 에이전트 이벤트(도구 호출/결과/최종 답변) 실시간 스트리밍
- `suggest` 모드에서 쓰기/셸 실행 시 뷰 안에서 **허용/거부** 승인
- 명령: `GigaChanie: 새 세션`, `GigaChanie: 작업 실행…`, `GigaChanie: 실행 취소`,
  `GigaChanie: 브리지 재시작`
- 설정: `gigachanie.command`, `gigachanie.mode`, `gigachanie.write`,
  `gigachanie.web`, `gigachanie.maxSteps`

## 프로토콜

`giga serve` 와 주고받는 JSON-RPC 2.0 메서드:

| 메서드 | 방향 | 설명 |
| --- | --- | --- |
| `initialize` | → | 버전/프로토콜/cwd |
| `session/new` | → | `{root, write, web, mode, maxSteps}` → `{sessionId, model, tools, mode}` |
| `session/prompt` | → | `{sessionId, text}` → `{ok, finalText, stopReason, steps, tokens, changedFiles}` |
| `session/cancel` | → | 실행 중인 프롬프트 취소 |
| `session/approve` | → | `{sessionId, requestId, decision}` (allow/deny/always) |
| `session/close` | → | 세션 종료 |
| `shutdown` | → | 브리지 종료 |
| `session/event` | ← | AgentEvent 스트림 `{kind, text, toolName, isError, step}` |
| `session/approval` | ← | `{requestId, kind, summary, detail, path}` |
