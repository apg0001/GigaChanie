import * as vscode from "vscode";
import { GigaClient } from "./rpc";

export function activate(context: vscode.ExtensionContext): void {
  const controller = new ChatController(context);
  const sidebar = new SidebarProvider(controller);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(SidebarProvider.viewId, sidebar, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.commands.registerCommand("gigachanie.openChat", () => controller.openPanel()),
    vscode.commands.registerCommand("gigachanie.newSession", () => controller.newSession()),
    vscode.commands.registerCommand("gigachanie.ask", () => controller.ask()),
    vscode.commands.registerCommand("gigachanie.cancel", () => controller.cancel()),
    vscode.commands.registerCommand("gigachanie.restart", () => controller.restart()),
    vscode.commands.registerCommand("gigachanie.resume", () => controller.resumeSession()),
    vscode.commands.registerCommand("gigachanie.pickModel", () => controller.pickModel()),
  );
}

export function deactivate(): void {
  /* 클라이언트는 ChatController.dispose 에서 정리 */
}

type OutMsg =
  | { type: "user"; text: string }
  | { type: "event"; kind: string; text?: string; toolName?: string; isError?: boolean }
  | { type: "final"; ok: boolean; stopReason: string; text: string; steps: number; total: number; changed: string[] }
  | { type: "approval"; requestId: string; kind: string; summary: string; detail: string; decided?: string }
  | { type: "ask"; requestId: string; question: string; options: string[]; allowCustom: boolean; answered?: string }
  | { type: "status"; text: string; busy: boolean }
  | { type: "settings"; model: string; mode: string; write: boolean; web: boolean }
  | { type: "completions"; frag: string; items: string[] }
  | { type: "clear" };

const REPLAYABLE = new Set(["user", "event", "final", "approval", "ask"]);
const HISTORY_CAP = 400;

/**
 * 하나의 대화 상태(브리지·세션·기록)를 들고, 붙어 있는 모든 웹뷰(사이드바 뷰 +
 * 에디터 탭 패널)에 같은 내용을 뿌린다. 어느 웹뷰에서 입력해도 같은 컨트롤러로 들어온다.
 */
class ChatController {
  private client: GigaClient | null = null;
  private sessionId: string | null = null;
  private pendingResume: string | null = null;
  private busy = false;
  private model = "";
  private mode = "";
  private web = false;
  private write = true;
  private readonly history: OutMsg[] = [];
  private readonly surfaces = new Set<vscode.Webview>();
  private panel: vscode.WebviewPanel | null = null;
  private readonly output: vscode.OutputChannel;
  private readonly status: vscode.StatusBarItem;

  constructor(context: vscode.ExtensionContext) {
    this.output = vscode.window.createOutputChannel("GigaChanie");
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
    this.status.command = "gigachanie.openChat";
    this.write = this.cfg().get<boolean>("write", true);
    this.web = this.cfg().get<boolean>("web", false);
    this.mode = this.cfg().get<string>("mode", "suggest");
    this.updateStatus();
    this.status.show();
    context.subscriptions.push(this.output, this.status, {
      dispose: () => this.client?.stop(),
    });
  }

  private cfg(): vscode.WorkspaceConfiguration {
    return vscode.workspace.getConfiguration("gigachanie");
  }

  private updateStatus(): void {
    const label = this.model ? `${this.model} · ${this.mode}` : "미연결";
    this.status.text = this.busy ? `$(sync~spin) GigaChanie` : `$(sparkle) GigaChanie: ${label}`;
    this.status.tooltip = this.busy ? "실행 중…" : "GigaChanie 채팅 열기";
  }

  // ---------------------------------------------------------------- 웹뷰 부착

  html(webview: vscode.Webview): string {
    return renderHtml(webview);
  }

  attach(webview: vscode.Webview): void {
    this.surfaces.add(webview);
    webview.onDidReceiveMessage((m) => this.onWebviewMessage(m));
    // 새로 붙은 웹뷰를 현재 상태로 채운다
    webview.postMessage({ type: "clear" } as OutMsg);
    for (const msg of this.history) {
      webview.postMessage(msg);
    }
    webview.postMessage(this.settingsSnapshot());
    webview.postMessage({
      type: "status",
      text: this.busy ? "실행 중…" : this.sessionId ? "대기" : "새 세션",
      busy: this.busy,
    } as OutMsg);
  }

  detach(webview: vscode.Webview): void {
    this.surfaces.delete(webview);
  }

  openPanel(): void {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      "gigachanie.chatTab",
      "GigaChanie",
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: false },
      { enableScripts: true, retainContextWhenHidden: true },
    );
    panel.webview.html = this.html(panel.webview);
    this.attach(panel.webview);
    panel.onDidDispose(() => {
      this.detach(panel.webview);
      this.panel = null;
    });
    this.panel = panel;
  }

  private post(msg: OutMsg): void {
    if (REPLAYABLE.has(msg.type)) {
      this.history.push(msg);
      if (this.history.length > HISTORY_CAP) {
        this.history.splice(0, this.history.length - HISTORY_CAP);
      }
    }
    if (msg.type === "clear") {
      this.history.length = 0;
    }
    for (const w of this.surfaces) {
      void w.postMessage(msg);
    }
  }

  private settingsSnapshot(): OutMsg {
    return { type: "settings", model: this.model, mode: this.mode, write: this.write, web: this.web };
  }

  private focusChat(): void {
    if (this.panel) {
      this.panel.reveal(this.panel.viewColumn ?? vscode.ViewColumn.Beside, true);
    } else {
      void vscode.commands.executeCommand("gigachanie.chat.focus");
    }
  }

  // ---------------------------------------------------------------- 입력 처리

  private onWebviewMessage(m: any): void {
    switch (m?.type) {
      case "submit":
        if (typeof m.text === "string") void this.submit(m.text.trim());
        break;
      case "approve":
        if (typeof m.requestId === "string") this.respondApproval(m.requestId, m.decision);
        break;
      case "answer":
        if (typeof m.requestId === "string") this.respondAsk(m.requestId, String(m.answer ?? ""));
        break;
      case "cancel":
        void this.cancel();
        break;
      case "openFile":
        if (typeof m.path === "string") void this.openFile(m.path, m.diff === true);
        break;
      case "complete":
        if (typeof m.frag === "string") void this.completeFiles(m.frag);
        break;
      case "setMode":
        void this.applySettings({ mode: String(m.value) });
        break;
      case "setWrite":
        void this.applySettings({ write: !!m.value });
        break;
      case "setWeb":
        void this.applySettings({ web: !!m.value });
        break;
      case "pickModel":
        void this.pickModel();
        break;
      case "newSession":
        void this.newSession();
        break;
      case "resume":
        void this.resumeSession();
        break;
      case "openSettings":
        void vscode.commands.executeCommand("workbench.action.openSettings", "gigachanie");
        break;
    }
  }

  // ---------------------------------------------------------------- 설정 변경

  private async applySettings(next: { mode?: string; write?: boolean; web?: boolean; model?: string }): Promise<void> {
    const cfg = this.cfg();
    const target = vscode.workspace.workspaceFolders?.length
      ? vscode.ConfigurationTarget.Workspace
      : vscode.ConfigurationTarget.Global;
    if (next.mode !== undefined && next.mode !== this.mode) {
      this.mode = next.mode;
      await cfg.update("mode", next.mode, target);
    }
    if (next.write !== undefined && next.write !== this.write) {
      this.write = next.write;
      await cfg.update("write", next.write, target);
    }
    if (next.web !== undefined && next.web !== this.web) {
      this.web = next.web;
      await cfg.update("web", next.web, target);
    }
    if (next.model !== undefined && next.model !== this.model) {
      this.model = next.model;
      await cfg.update("model", next.model, target);
    }
    // 진행 중이 아니면 세션을 새로 열어 바뀐 설정을 즉시 반영
    if (!this.busy) {
      await this.closeSession();
      this.post({ type: "status", text: "설정 변경됨 · 새 세션", busy: false });
    } else {
      this.post({ type: "status", text: "설정 변경됨 · 다음 세션부터 적용", busy: true });
    }
    this.post(this.settingsSnapshot());
  }

  async pickModel(): Promise<void> {
    const root = this.workspaceRoot();
    if (!root) {
      vscode.window.showErrorMessage("워크스페이스 폴더를 먼저 열어주세요.");
      return;
    }
    let models: any[] = [];
    let current = this.model;
    try {
      const client = this.ensureClient(root);
      const r = await client.request<{ current: string; models: any[] }>("models/list", {});
      models = r.models ?? [];
      current = r.current || current;
    } catch (err: any) {
      vscode.window.showErrorMessage(`모델 목록을 불러오지 못했습니다: ${err?.message ?? err}`);
      return;
    }
    const items: (vscode.QuickPickItem & { id: string })[] = models.map((m) => ({
      label: (m.installed ? "$(check) " : "$(cloud-download) ") + m.id,
      description: [m.params, m.fit, m.installed ? "" : "미설치"].filter(Boolean).join(" · "),
      detail: m.display,
      id: m.id,
      picked: m.id === current,
    }));
    const pick = await vscode.window.showQuickPick(items, {
      title: "GigaChanie 모델 선택",
      placeHolder: "$(check) 설치됨 · $(cloud-download) 첫 사용 시 자동 다운로드",
    });
    if (!pick) {
      return;
    }
    const asDefault = await vscode.window.showQuickPick(["이 세션만", "기본값으로 저장 (giga chat 등과 공유)"], {
      title: `모델: ${pick.id}`,
    });
    if (!asDefault) {
      return;
    }
    if (asDefault.startsWith("기본값")) {
      try {
        await this.ensureClient(this.workspaceRoot()!).request("models/use", { model: pick.id });
      } catch (err: any) {
        this.output.appendLine(`기본 모델 저장 실패: ${err?.message ?? err}`);
      }
    }
    await this.applySettings({ model: pick.id });
  }

  // ---------------------------------------------------------------- 연결/세션

  private workspaceRoot(): string | null {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? null;
  }

  private ensureClient(root: string): GigaClient {
    if (this.client && this.client.running) {
      return this.client;
    }
    const cmd = this.cfg().get<string>("command", "giga");
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
      if (this.surfaces.size > 0) {
        // 채팅 안에 질문 카드로 표시 (상단 팝업 대신)
        this.post({
          type: "ask",
          requestId: params.requestId,
          question: String(params.question ?? ""),
          options: Array.isArray(params.options) ? params.options.map(String) : [],
          allowCustom: params.allowCustom !== false,
        });
        this.focusChat();
      } else {
        void this.handleAskFallback(params);
      }
    }
  }

  /** 열린 채팅 화면이 하나도 없을 때만 쓰는 QuickPick 폴백. */
  private async handleAskFallback(params: any): Promise<void> {
    const options: string[] = Array.isArray(params.options) ? params.options : [];
    const custom = "$(edit) 직접 입력…";
    const items = params.allowCustom ? [...options, custom] : options;
    let answer = "";
    if (items.length > 0) {
      const picked = await vscode.window.showQuickPick(items, {
        title: "GigaChanie", placeHolder: params.question, ignoreFocusOut: true,
      });
      answer = picked === custom || picked === undefined ? "" : picked;
    }
    if (!answer && params.allowCustom !== false) {
      answer =
        (await vscode.window.showInputBox({
          title: "GigaChanie", prompt: params.question, ignoreFocusOut: true,
        })) ?? "";
    }
    this.respondAsk(params.requestId, answer);
  }

  private respondAsk(requestId: string, answer: string): void {
    for (const msg of this.history) {
      if (msg.type === "ask" && msg.requestId === requestId) {
        msg.answered = answer || "(가정하고 진행)";
      }
    }
    if (!this.client || !this.sessionId) {
      return;
    }
    try {
      this.client.notify("session/answer", { sessionId: this.sessionId, requestId, answer });
    } catch (err: any) {
      this.output.appendLine(`답변 전달 실패: ${err?.message ?? err}`);
    }
  }

  private async ensureSession(client: GigaClient, root: string): Promise<string> {
    if (this.sessionId) {
      return this.sessionId;
    }
    const cfg = this.cfg();
    const think = cfg.get<string>("think", "off");
    const model = cfg.get<string>("model", "");
    const res = await client.request<{
      sessionId: string;
      model: string;
      mode: string;
      web?: boolean;
      writable?: boolean;
      resumedTurns?: number;
    }>("session/new", {
      root,
      write: this.write,
      web: this.web,
      mode: this.mode,
      model: model || undefined,
      maxSteps: cfg.get<number>("maxSteps", 20),
      prompts: cfg.get<string[]>("prompts", []),
      think: think === "think",
      thinkHard: think === "think-hard",
      resume: this.pendingResume ?? undefined,
    });
    this.pendingResume = null;
    this.sessionId = res.sessionId;
    this.model = res.model;
    this.mode = res.mode;
    if (typeof res.web === "boolean") this.web = res.web;
    if (typeof res.writable === "boolean") this.write = res.writable;
    this.updateStatus();
    this.post(this.settingsSnapshot());
    const rt = res.resumedTurns ? ` · ${res.resumedTurns}턴 이어감` : "";
    this.post({ type: "status", text: `세션 시작 · ${res.model} · ${res.mode}${rt}`, busy: false });
    return res.sessionId;
  }

  private async closeSession(): Promise<void> {
    if (this.client && this.sessionId) {
      try {
        await this.client.request("session/close", { sessionId: this.sessionId });
      } catch {
        /* ignore */
      }
    }
    this.sessionId = null;
  }

  async resumeSession(): Promise<void> {
    const root = this.workspaceRoot();
    if (!root) {
      vscode.window.showErrorMessage("워크스페이스 폴더를 먼저 열어주세요.");
      return;
    }
    const client = this.ensureClient(root);
    let items: any[] = [];
    try {
      const r = await client.request<{ sessions: any[] }>("session/history", { root });
      items = r.sessions ?? [];
    } catch (err: any) {
      vscode.window.showErrorMessage(`세션 목록을 불러오지 못했습니다: ${err?.message ?? err}`);
      return;
    }
    if (items.length === 0) {
      vscode.window.showInformationMessage("저장된 세션이 없습니다.");
      return;
    }
    const pick = await vscode.window.showQuickPick(
      items.map((s) => ({
        label: s.title || "(제목 없음)",
        description: `${s.turns}턴 · ${s.model ?? ""}`,
        id: s.id as string,
      })),
      { title: "이어갈 GigaChanie 세션" },
    );
    if (!pick) {
      return;
    }
    await this.closeSession();
    this.pendingResume = pick.id;
    this.post({ type: "clear" });
    this.post({ type: "status", text: `"${pick.label}" 이어감 (다음 메시지부터)`, busy: false });
    this.focusChat();
  }

  // ---------------------------------------------------------------- 동작

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
    // 기록에서 해당 승인 항목을 '결정됨' 으로 바꿔, 나중에 붙는 웹뷰엔 버튼 대신 결과가 보이게
    for (const msg of this.history) {
      if (msg.type === "approval" && msg.requestId === requestId) {
        msg.decided = decision;
      }
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
    await this.closeSession();
    this.post({ type: "clear" });
    this.post({ type: "status", text: "새 세션", busy: false });
    this.post(this.settingsSnapshot());
  }

  async ask(): Promise<void> {
    const text = await vscode.window.showInputBox({
      prompt: "GigaChanie 에게 시킬 작업",
      placeHolder: "예: 이 파일의 버그를 찾아서 고쳐줘",
    });
    if (text) {
      this.focusChat();
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

  private async openFile(rel: string, diff: boolean): Promise<void> {
    const root = this.workspaceRoot();
    if (!root) {
      return;
    }
    const uri = vscode.Uri.joinPath(vscode.Uri.file(root), rel);
    try {
      if (diff) {
        await vscode.commands.executeCommand("git.openChange", uri);
      } else {
        await vscode.window.showTextDocument(uri, { preview: false });
      }
    } catch (err: any) {
      this.output.appendLine(`파일 열기 실패 (${rel}): ${err?.message ?? err}`);
    }
  }

  private async completeFiles(frag: string): Promise<void> {
    const clean = frag.replace(/[^\w./\-가-힣]/g, "");
    const pattern = clean ? `**/*${clean}*` : "**/*";
    let uris: vscode.Uri[] = [];
    try {
      uris = await vscode.workspace.findFiles(
        pattern,
        "**/{node_modules,.git,out,dist,build,.venv}/**",
        30,
      );
    } catch {
      /* ignore */
    }
    const root = this.workspaceRoot() ?? "";
    const items = uris
      .map((u) => vscode.workspace.asRelativePath(u, false))
      .filter((p) => root === "" || !p.startsWith(".."))
      .sort();
    this.post({ type: "completions", frag, items });
  }
}

class SidebarProvider implements vscode.WebviewViewProvider {
  static readonly viewId = "gigachanie.chat";
  constructor(private readonly controller: ChatController) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    view.webview.options = { enableScripts: true };
    view.webview.html = this.controller.html(view.webview);
    this.controller.attach(view.webview);
    view.onDidDispose(() => this.controller.detach(view.webview));
  }
}

// -------------------------------------------------------------------- HTML

function renderHtml(webview: vscode.Webview): string {
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
  #head { display: flex; align-items: center; gap: 4px; padding: 5px 6px; flex-wrap: wrap;
    border-bottom: 1px solid var(--vscode-panel-border); }
  #head select, #head button { font-family: inherit; font-size: 0.85em; }
  #head select { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground);
    border: 1px solid var(--vscode-dropdown-border); border-radius: 4px; padding: 2px 4px; }
  .chip { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground);
    border: none; border-radius: 4px; padding: 3px 8px; cursor: pointer; }
  .chip.on { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  #model { max-width: 46%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #head .spacer { flex: 1; }
  #head .icon { padding: 3px 6px; }
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
  #wrap { position: relative; flex: 1; display: flex; }
  #ac { position: absolute; bottom: 100%; left: 0; right: 0; margin: 0 0 2px; padding: 2px;
    list-style: none; max-height: 180px; overflow-y: auto; z-index: 5;
    background: var(--vscode-editorWidget-background); border: 1px solid var(--vscode-editorWidget-border);
    border-radius: 4px; font-family: var(--vscode-editor-font-family); font-size: 0.9em; }
  #ac li { padding: 2px 6px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #ac li.sel, #ac li:hover { background: var(--vscode-list-activeSelectionBackground);
    color: var(--vscode-list-activeSelectionForeground); }
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
  <div id="head">
    <button id="model" class="chip" title="모델 선택">모델…</button>
    <select id="mode" title="승인 모드">
      <option value="suggest">suggest</option>
      <option value="auto-edit">auto-edit</option>
      <option value="full-auto">full-auto</option>
    </select>
    <button id="write" class="chip" title="파일 쓰기/실행 도구">write</button>
    <button id="web" class="chip" title="웹 검색/가져오기 도구">web</button>
    <span class="spacer"></span>
    <button id="new" class="chip icon" title="새 세션">＋</button>
    <button id="resume" class="chip icon" title="이전 세션 이어가기">↺</button>
    <button id="gear" class="chip icon" title="전체 설정">⚙</button>
  </div>
  <div id="log"></div>
  <div id="status">대기</div>
  <div id="bar">
    <div id="wrap">
      <textarea id="input" placeholder="작업을 입력하고 Enter (줄바꿈은 Shift+Enter). @파일 자동완성"></textarea>
      <ul id="ac" hidden></ul>
    </div>
    <button id="send">보내기</button>
  </div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const log = document.getElementById('log');
  const input = document.getElementById('input');
  const statusEl = document.getElementById('status');
  const modelBtn = document.getElementById('model');
  const modeSel = document.getElementById('mode');
  const writeBtn = document.getElementById('write');
  const webBtn = document.getElementById('web');
  let current = null;

  modelBtn.addEventListener('click', () => vscode.postMessage({ type: 'pickModel' }));
  modeSel.addEventListener('change', () => vscode.postMessage({ type: 'setMode', value: modeSel.value }));
  writeBtn.addEventListener('click', () =>
    vscode.postMessage({ type: 'setWrite', value: !writeBtn.classList.contains('on') }));
  webBtn.addEventListener('click', () =>
    vscode.postMessage({ type: 'setWeb', value: !webBtn.classList.contains('on') }));
  document.getElementById('new').addEventListener('click', () => vscode.postMessage({ type: 'newSession' }));
  document.getElementById('resume').addEventListener('click', () => vscode.postMessage({ type: 'resume' }));
  document.getElementById('gear').addEventListener('click', () => vscode.postMessage({ type: 'openSettings' }));

  function applySettings(m) {
    modelBtn.textContent = m.model || '모델…';
    modelBtn.title = '모델: ' + (m.model || '(미설정)');
    modeSel.value = m.mode || 'suggest';
    writeBtn.classList.toggle('on', !!m.write);
    webBtn.classList.toggle('on', !!m.web);
  }

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
    hideAc();
    vscode.postMessage({ type: 'submit', text });
  }
  document.getElementById('send').addEventListener('click', send);

  const ac = document.getElementById('ac');
  let acItems = [];
  let acSel = -1;
  let acFrag = '';

  function hideAc() { ac.hidden = true; acItems = []; acSel = -1; }
  function currentFrag() {
    const upto = input.value.slice(0, input.selectionStart);
    const mt = upto.match(/@([\\w./\\-가-힣]*)$/);
    return mt ? mt[1] : null;
  }
  function applyAc(item) {
    const start = input.selectionStart - acFrag.length;
    input.value = input.value.slice(0, start) + item + ' ' + input.value.slice(input.selectionStart);
    const pos = start + item.length + 1;
    input.setSelectionRange(pos, pos);
    hideAc();
    input.focus();
  }
  function renderAc() {
    ac.innerHTML = '';
    acItems.slice(0, 50).forEach((it, i) => {
      const li = document.createElement('li');
      li.textContent = it;
      if (i === acSel) li.className = 'sel';
      li.addEventListener('mousedown', (e) => { e.preventDefault(); applyAc(it); });
      ac.appendChild(li);
    });
    ac.hidden = acItems.length === 0;
  }

  input.addEventListener('input', () => {
    const f = currentFrag();
    if (f === null) { hideAc(); return; }
    acFrag = f;
    vscode.postMessage({ type: 'complete', frag: f });
  });
  input.addEventListener('keydown', (e) => {
    if (!ac.hidden && acItems.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); acSel = (acSel + 1) % acItems.length; renderAc(); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); acSel = (acSel - 1 + acItems.length) % acItems.length; renderAc(); return; }
      if (e.key === 'Tab' || (e.key === 'Enter' && acSel >= 0)) {
        e.preventDefault(); applyAc(acItems[acSel < 0 ? 0 : acSel]); return;
      }
      if (e.key === 'Escape') { e.preventDefault(); hideAc(); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  input.addEventListener('blur', () => setTimeout(hideAc, 120));

  function renderAsk(m) {
    const d = document.createElement('div');
    d.className = 'msg approval';
    const h = document.createElement('div');
    h.textContent = '질문: ' + m.question;
    d.appendChild(h);
    if (m.answered) {
      const s = document.createElement('div');
      s.className = 'meta';
      s.textContent = '→ ' + m.answered;
      d.appendChild(s);
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
      return;
    }
    const row = document.createElement('div');
    row.style.marginTop = '6px';
    const finish = (answer) => {
      row.querySelectorAll('button,input').forEach((el) => (el.disabled = true));
      vscode.postMessage({ type: 'answer', requestId: m.requestId, answer });
    };
    (m.options || []).forEach((opt) => {
      const b = document.createElement('button');
      b.textContent = opt;
      b.style.marginRight = '6px';
      b.addEventListener('click', () => finish(opt));
      row.appendChild(b);
    });
    d.appendChild(row);
    if (m.allowCustom !== false) {
      const wrap2 = document.createElement('div');
      wrap2.style.cssText = 'display:flex;gap:6px;margin-top:6px';
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.placeholder = '직접 입력…';
      inp.style.cssText = 'flex:1;background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border);border-radius:4px;padding:4px';
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); finish(inp.value.trim()); } });
      const ok = document.createElement('button');
      ok.textContent = '보내기';
      ok.addEventListener('click', () => finish(inp.value.trim()));
      wrap2.appendChild(inp); wrap2.appendChild(ok);
      d.appendChild(wrap2);
      setTimeout(() => inp.focus(), 0);
    }
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  function renderApproval(m) {
    const d = document.createElement('div');
    d.className = 'msg approval';
    const h = document.createElement('div');
    h.textContent = '승인 필요 (' + m.kind + '): ' + m.summary;
    d.appendChild(h);
    if (m.detail) { const pre = document.createElement('pre'); pre.textContent = m.detail; d.appendChild(pre); }
    if (m.decided) {
      const s = document.createElement('div');
      s.className = 'meta';
      s.textContent = m.decided === 'deny' ? '→ 거부됨' : '→ 허용됨';
      d.appendChild(s);
    } else {
      const allow = document.createElement('button');
      allow.textContent = '허용';
      const deny = document.createElement('button');
      deny.textContent = '거부'; deny.className = 'secondary';
      const done = (decision) => { allow.disabled = deny.disabled = true;
        vscode.postMessage({ type: 'approve', requestId: m.requestId, decision }); };
      allow.addEventListener('click', () => done('allow'));
      deny.addEventListener('click', () => done('deny'));
      d.appendChild(allow); d.appendChild(deny);
    }
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  window.addEventListener('message', (ev) => {
    const m = ev.data;
    if (m.type === 'clear') { log.innerHTML = ''; current = null; tasksEl = null; }
    else if (m.type === 'settings') { applySettings(m); }
    else if (m.type === 'user') { add('user', m.text); current = null; }
    else if (m.type === 'status') { statusEl.textContent = m.text; }
    else if (m.type === 'completions') {
      if (m.frag !== acFrag) return;
      acItems = m.items || []; acSel = acItems.length ? 0 : -1; renderAc();
    }
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
      else if (m.kind === 'tool_output') {
        if (!current || !current.classList.contains('tool')) { current = add('tool', ''); }
        current.textContent += m.text || '';
        log.scrollTop = log.scrollHeight;
      }
      else if (m.kind === 'tool_result') {
        if (m.toolName === 'update_tasks' && !m.isError) { renderTasks(m.text || ''); return; }
        add('tool' + (m.isError ? ' err' : ''), (m.text || '').slice(0, 2000));
        current = null;
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
          if (i) files.appendChild(document.createTextNode(' · '));
          const a = document.createElement('a');
          a.href = '#'; a.textContent = p;
          a.addEventListener('click', (e) => { e.preventDefault();
            vscode.postMessage({ type: 'openFile', path: p }); });
          files.appendChild(a);
          const dl = document.createElement('a');
          dl.href = '#'; dl.textContent = ' (diff)';
          dl.addEventListener('click', (e) => { e.preventDefault();
            vscode.postMessage({ type: 'openFile', path: p, diff: true }); });
          files.appendChild(dl);
        });
        d.appendChild(files);
      }
      current = null;
    }
    else if (m.type === 'approval') { renderApproval(m); }
    else if (m.type === 'ask') { renderAsk(m); }
  });
</script>
</body>
</html>`;
}
