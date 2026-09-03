import * as vscode from "vscode";
import { GigaClient } from "./rpc";

export function activate(context: vscode.ExtensionContext): void {
  const provider = new ChatViewProvider(context);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewId, provider),
    vscode.commands.registerCommand("gigachanie.newSession", () => provider.newSession()),
    vscode.commands.registerCommand("gigachanie.ask", () => provider.ask()),
    vscode.commands.registerCommand("gigachanie.cancel", () => provider.cancel()),
    vscode.commands.registerCommand("gigachanie.restart", () => provider.restart()),
  );
}

export function deactivate(): void {
  /* 클라이언트는 ChatViewProvider.dispose 에서 정리 */
}

type OutMsg =
  | { type: "user"; text: string }
  | { type: "event"; kind: string; text?: string; toolName?: string; isError?: boolean }
  | { type: "final"; ok: boolean; stopReason: string; text: string; steps: number; total: number; changed: string[] }
  | { type: "approval"; requestId: string; kind: string; summary: string; detail: string }
  | { type: "status"; text: string; busy: boolean }
  | { type: "clear" };

class ChatViewProvider implements vscode.WebviewViewProvider {
  static readonly viewId = "gigachanie.chat";

  private view: vscode.WebviewView | null = null;
  private client: GigaClient | null = null;
  private sessionId: string | null = null;
  private busy = false;
  private model = "";
  private mode = "";
  private readonly output: vscode.OutputChannel;
  private readonly status: vscode.StatusBarItem;

  constructor(context: vscode.ExtensionContext) {
    this.output = vscode.window.createOutputChannel("GigaChanie");
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
    this.status.command = "gigachanie.chat.focus";
    this.updateStatus();
    this.status.show();
    context.subscriptions.push(this.output, this.status, {
      dispose: () => this.client?.stop(),
    });
  }

  private updateStatus(): void {
    const label = this.model ? `${this.model} · ${this.mode}` : "미연결";
    this.status.text = this.busy ? `$(sync~spin) GigaChanie` : `$(sparkle) GigaChanie: ${label}`;
    this.status.tooltip = this.busy ? "실행 중…" : "GigaChanie 채팅 열기";
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage((m) => this.onWebviewMessage(m));
  }

  private post(msg: OutMsg): void {
    this.view?.webview.postMessage(msg);
  }

  private onWebviewMessage(m: any): void {
    if (m?.type === "submit" && typeof m.text === "string") {
      void this.submit(m.text.trim());
    } else if (m?.type === "approve" && typeof m.requestId === "string") {
      this.respondApproval(m.requestId, m.decision);
    } else if (m?.type === "cancel") {
      void this.cancel();
    } else if (m?.type === "openFile" && typeof m.path === "string") {
      void this.openFile(m.path);
    }
  }

  private async openFile(rel: string): Promise<void> {
    const root = this.workspaceRoot();
    if (!root) {
      return;
    }
    const uri = vscode.Uri.joinPath(vscode.Uri.file(root), rel);
    try {
      await vscode.window.showTextDocument(uri, { preview: false });
    } catch (err: any) {
      this.output.appendLine(`파일 열기 실패 (${rel}): ${err?.message ?? err}`);
    }
  }

  // ------------------------------------------------------------------ 연결

  private workspaceRoot(): string | null {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? null;
  }

  private ensureClient(root: string): GigaClient {
    if (this.client && this.client.running) {
      return this.client;
    }
    const cmd = vscode.workspace.getConfiguration("gigachanie").get<string>("command", "giga");
    const client = new GigaClient(cmd, root);
    client.on("log", (line: string) => this.output.appendLine(line));
    client.on("error", (err: Error) => {
      this.output.appendLine(`오류: ${err.message}`);
      vscode.window.showErrorMessage(
        `GigaChanie 브리지를 시작할 수 없습니다: ${err.message} (설정 gigachanie.command 확인)`,
      );
    });
    client.on("exit", (code: number) => {
      this.output.appendLine(`브리지 종료 (code ${code})`);
      this.sessionId = null;
      this.setBusy(false);
    });
    client.on("notification", (method: string, params: any) => this.onNotification(method, params));
    client.start();
    this.client = client;
    return client;
  }

  private onNotification(method: string, params: any): void {
    if (method === "session/event") {
      this.post({
        type: "event",
        kind: params.kind,
        text: params.text,
        toolName: params.toolName,
        isError: params.isError,
      });
    } else if (method === "session/approval") {
      this.post({
        type: "approval",
        requestId: params.requestId,
        kind: params.kind,
        summary: params.summary,
        detail: params.detail ?? "",
      });
    } else if (method === "session/ask") {
      void this.handleAsk(params);
    }
  }

  private async handleAsk(params: any): Promise<void> {
    if (!this.client || !this.sessionId) {
      return;
    }
    const options: string[] = Array.isArray(params.options) ? params.options : [];
    const custom = "$(edit) 직접 입력…";
    const items = params.allowCustom ? [...options, custom] : options;
    let answer = "";
    if (items.length > 0) {
      const picked = await vscode.window.showQuickPick(items, {
        title: "GigaChanie",
        placeHolder: params.question,
        ignoreFocusOut: true,
      });
      answer = picked === custom || picked === undefined ? "" : picked;
    }
    if (!answer && params.allowCustom !== false) {
      answer =
        (await vscode.window.showInputBox({
          title: "GigaChanie",
          prompt: params.question,
          ignoreFocusOut: true,
        })) ?? "";
    }
    try {
      this.client.notify("session/answer", {
        sessionId: this.sessionId,
        requestId: params.requestId,
        answer,
      });
    } catch (err: any) {
      this.output.appendLine(`답변 전달 실패: ${err?.message ?? err}`);
    }
  }

  private async ensureSession(client: GigaClient, root: string): Promise<string> {
    if (this.sessionId) {
      return this.sessionId;
    }
    const cfg = vscode.workspace.getConfiguration("gigachanie");
    const res = await client.request<{ sessionId: string; model: string; mode: string }>(
      "session/new",
      {
        root,
        write: cfg.get<boolean>("write", true),
        web: cfg.get<boolean>("web", false),
        mode: cfg.get<string>("mode", "suggest"),
        maxSteps: cfg.get<number>("maxSteps", 20),
      },
    );
    this.sessionId = res.sessionId;
    this.model = res.model;
    this.mode = res.mode;
    this.updateStatus();
    this.post({ type: "status", text: `세션 시작 · ${res.model} · ${res.mode}`, busy: false });
    return res.sessionId;
  }

  // ------------------------------------------------------------------ 동작

  private setBusy(busy: boolean): void {
    this.busy = busy;
    this.updateStatus();
    this.post({ type: "status", text: busy ? "실행 중…" : "대기", busy });
  }

  private async submit(text: string): Promise<void> {
    if (!text) {
      return;
    }
    if (this.busy) {
      vscode.window.showWarningMessage("이미 실행 중입니다. 취소 후 다시 시도하세요.");
      return;
    }
    const root = this.workspaceRoot();
    if (!root) {
      vscode.window.showErrorMessage("워크스페이스 폴더를 먼저 열어주세요.");
      return;
    }
    this.post({ type: "user", text });
    this.setBusy(true);
    try {
      const client = this.ensureClient(root);
      const sessionId = await this.ensureSession(client, root);
      const r = await client.request<any>("session/prompt", { sessionId, text });
      this.post({
        type: "final",
        ok: r.ok,
        stopReason: r.stopReason,
        text: r.finalText ?? "",
        steps: r.steps ?? 0,
        total: r.tokens?.total ?? 0,
        changed: r.changedFiles ?? [],
      });
    } catch (err: any) {
      this.post({ type: "event", kind: "error", text: String(err?.message ?? err), isError: true });
    } finally {
      this.setBusy(false);
    }
  }

  private respondApproval(requestId: string, decision: string): void {
    if (!this.client || !this.sessionId) {
      return;
    }
    try {
      this.client.notify("session/approve", { sessionId: this.sessionId, requestId, decision });
    } catch (err: any) {
      this.output.appendLine(`승인 전달 실패: ${err?.message ?? err}`);
    }
  }

  async cancel(): Promise<void> {
    if (this.client && this.sessionId && this.busy) {
      try {
        await this.client.request("session/cancel", { sessionId: this.sessionId });
      } catch {
        /* ignore */
      }
    }
  }

  async newSession(): Promise<void> {
    if (this.client && this.sessionId) {
      try {
        await this.client.request("session/close", { sessionId: this.sessionId });
      } catch {
        /* ignore */
      }
    }
    this.sessionId = null;
    this.post({ type: "clear" });
    this.post({ type: "status", text: "새 세션", busy: false });
  }

  async ask(): Promise<void> {
    const text = await vscode.window.showInputBox({
      prompt: "GigaChanie 에게 시킬 작업",
      placeHolder: "예: 이 파일의 버그를 찾아서 고쳐줘",
    });
    if (text) {
      await vscode.commands.executeCommand("gigachanie.chat.focus");
      void this.submit(text.trim());
    }
  }

  restart(): void {
    this.client?.stop();
    this.client = null;
    this.sessionId = null;
    this.post({ type: "clear" });
    vscode.window.showInformationMessage("GigaChanie 브리지를 재시작했습니다.");
  }

  // ------------------------------------------------------------------ HTML

  private html(webview: vscode.Webview): string {
    const nonce = String(Math.random()).slice(2);
    const csp = `default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';`;
    return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; font-family: var(--vscode-font-family); font-size: var(--vscode-font-size);
    color: var(--vscode-foreground); display: flex; flex-direction: column; height: 100vh; }
  #log { flex: 1; overflow-y: auto; padding: 10px; }
  .msg { margin: 8px 0; padding: 8px 10px; border-radius: 6px; white-space: pre-wrap; word-break: break-word; }
  .user { background: var(--vscode-textBlockQuote-background); border-left: 3px solid var(--vscode-focusBorder); }
  .assistant { background: var(--vscode-editor-inactiveSelectionBackground); }
  .tool { font-family: var(--vscode-editor-font-family); font-size: 0.9em; opacity: 0.85; }
  .tasks { background: var(--vscode-editor-inactiveSelectionBackground); font-size: 0.95em; }
  .tasks > div { padding: 1px 0; }
  .tool.err { color: var(--vscode-errorForeground); }
  .final { border-top: 1px dashed var(--vscode-panel-border); padding-top: 6px; }
  .meta { opacity: 0.7; font-size: 0.85em; margin-top: 4px; }
  .meta a { color: var(--vscode-textLink-foreground); cursor: pointer; }
  .approval { background: var(--vscode-inputValidation-warningBackground);
    border: 1px solid var(--vscode-inputValidation-warningBorder); }
  .approval pre { max-height: 180px; overflow: auto; background: var(--vscode-editor-background); padding: 6px; }
  .approval button { margin-right: 6px; }
  #bar { display: flex; gap: 6px; padding: 8px; border-top: 1px solid var(--vscode-panel-border); }
  #input { flex: 1; resize: none; min-height: 44px; max-height: 160px;
    background: var(--vscode-input-background); color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border); border-radius: 4px; padding: 6px; font-family: inherit; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground);
    border: none; border-radius: 4px; padding: 4px 12px; cursor: pointer; }
  button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
  #status { padding: 2px 10px; font-size: 0.85em; opacity: 0.7; }
</style>
</head>
<body>
  <div id="log"></div>
  <div id="status">대기</div>
  <div id="bar">
    <textarea id="input" placeholder="작업을 입력하고 Enter (줄바꿈은 Shift+Enter)"></textarea>
    <button id="send">보내기</button>
  </div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const log = document.getElementById('log');
  const input = document.getElementById('input');
  const statusEl = document.getElementById('status');
  let current = null;

  function add(cls, text) {
    const d = document.createElement('div');
    d.className = 'msg ' + cls;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  let tasksEl = null;
  function renderTasks(text) {
    if (!tasksEl || !tasksEl.isConnected) { tasksEl = add('tasks', ''); }
    tasksEl.textContent = '';
    text.split('\\n').forEach((line) => {
      const s = line.trim();
      const row = document.createElement('div');
      if (s.startsWith('[x]')) { row.textContent = '✔ ' + s.slice(3).trim(); row.style.opacity = '0.6'; }
      else if (s.startsWith('[~]')) { row.textContent = '▶ ' + s.slice(3).trim(); row.style.fontWeight = '600'; }
      else if (s.startsWith('[ ]')) { row.textContent = '○ ' + s.slice(3).trim(); }
      else if (s.startsWith('—')) { row.textContent = s; row.style.opacity = '0.6'; row.style.fontSize = '0.9em'; }
      else return;
      tasksEl.appendChild(row);
    });
    log.scrollTop = log.scrollHeight;
  }

  function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    vscode.postMessage({ type: 'submit', text });
  }
  document.getElementById('send').addEventListener('click', send);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

  window.addEventListener('message', (ev) => {
    const m = ev.data;
    if (m.type === 'clear') { log.innerHTML = ''; current = null; }
    else if (m.type === 'user') { add('user', m.text); current = null; }
    else if (m.type === 'status') { statusEl.textContent = m.text; }
    else if (m.type === 'event') {
      if (m.kind === 'assistant_text') { current = add('assistant', m.text || ''); }
      else if (m.kind === 'assistant_delta') {
        if (!current) current = add('assistant', '');
        current.textContent += m.text || '';
        log.scrollTop = log.scrollHeight;
      }
      else if (m.kind === 'tool_call') {
        if (m.toolName === 'update_tasks') { current = null; return; }
        add('tool', '→ ' + (m.toolName || 'tool')); current = null;
      }
      else if (m.kind === 'tool_result') {
        if (m.toolName === 'update_tasks' && !m.isError) { renderTasks(m.text || ''); return; }
        add('tool' + (m.isError ? ' err' : ''), (m.text || '').slice(0, 2000));
      }
      else if (m.kind === 'compact') { add('tool', m.text || '대화 압축'); }
      else if (m.kind === 'error') { add('tool err', m.text || '오류'); }
    }
    else if (m.type === 'final') {
      const d = add('assistant final', m.text || '(빈 응답)');
      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.textContent = '스텝 ' + m.steps + ' · ' + m.stopReason + ' · 토큰 ' + m.total;
      d.appendChild(meta);
      if (m.changed && m.changed.length) {
        const files = document.createElement('div');
        files.className = 'meta';
        files.appendChild(document.createTextNode('변경: '));
        m.changed.forEach((p, i) => {
          if (i) files.appendChild(document.createTextNode(', '));
          const a = document.createElement('a');
          a.href = '#'; a.textContent = p;
          a.addEventListener('click', (e) => { e.preventDefault();
            vscode.postMessage({ type: 'openFile', path: p }); });
          files.appendChild(a);
        });
        d.appendChild(files);
      }
      current = null;
    }
    else if (m.type === 'approval') {
      const d = document.createElement('div');
      d.className = 'msg approval';
      const h = document.createElement('div');
      h.textContent = '승인 필요 (' + m.kind + '): ' + m.summary;
      d.appendChild(h);
      if (m.detail) { const pre = document.createElement('pre'); pre.textContent = m.detail; d.appendChild(pre); }
      const allow = document.createElement('button');
      allow.textContent = '허용';
      const deny = document.createElement('button');
      deny.textContent = '거부'; deny.className = 'secondary';
      const done = (decision) => { allow.disabled = deny.disabled = true;
        vscode.postMessage({ type: 'approve', requestId: m.requestId, decision }); };
      allow.addEventListener('click', () => done('allow'));
      deny.addEventListener('click', () => done('deny'));
      d.appendChild(allow); d.appendChild(deny);
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
    }
  });
</script>
</body>
</html>`;
  }
}
