import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import { EventEmitter } from "events";

type Pending = {
  resolve: (value: any) => void;
  reject: (reason: any) => void;
};

/**
 * `giga serve` 자식 프로세스와 줄 단위 JSON-RPC 2.0 로 통신하는 클라이언트.
 *
 * - `request(method, params)` : 응답이 올 때까지 기다리는 요청
 * - `notify(method, params)`  : 응답을 기다리지 않는 알림
 * - 이벤트: `notification`(서버 알림), `exit`, `error`, `log`(stderr 한 줄)
 */
export class GigaClient extends EventEmitter {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private buffer = "";

  constructor(
    private readonly command: string,
    private readonly cwd: string,
  ) {
    super();
  }

  get running(): boolean {
    return this.proc !== null && this.proc.exitCode === null;
  }

  start(): void {
    if (this.running) {
      return;
    }
    const proc = spawn(this.command, ["serve"], {
      cwd: this.cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.proc = proc;

    proc.stdout.setEncoding("utf8");
    proc.stdout.on("data", (chunk: string) => this.onStdout(chunk));

    proc.stderr.setEncoding("utf8");
    proc.stderr.on("data", (chunk: string) => {
      for (const line of chunk.split(/\r?\n/)) {
        if (line.trim()) {
          this.emit("log", line);
        }
      }
    });

    proc.on("error", (err) => this.emit("error", err));
    proc.on("exit", (code) => {
      this.proc = null;
      for (const [, p] of this.pending) {
        p.reject(new Error(`giga serve 프로세스가 종료되었습니다 (code ${code})`));
      }
      this.pending.clear();
      this.emit("exit", code);
    });
  }

  stop(): void {
    if (this.proc) {
      try {
        this.notify("shutdown", {});
      } catch {
        /* ignore */
      }
      this.proc.kill();
      this.proc = null;
    }
  }

  request<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (!this.proc) {
      return Promise.reject(new Error("브리지가 실행 중이 아닙니다."));
    }
    const id = this.nextId++;
    const payload = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.proc!.stdin.write(payload + "\n");
    });
  }

  notify(method: string, params: Record<string, unknown> = {}): void {
    if (!this.proc) {
      throw new Error("브리지가 실행 중이 아닙니다.");
    }
    this.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n");
  }

  private onStdout(chunk: string): void {
    this.buffer += chunk;
    let idx: number;
    while ((idx = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, idx).trim();
      this.buffer = this.buffer.slice(idx + 1);
      if (!line) {
        continue;
      }
      let msg: any;
      try {
        msg = JSON.parse(line);
      } catch {
        this.emit("log", `JSON 파싱 실패: ${line.slice(0, 200)}`);
        continue;
      }
      this.handle(msg);
    }
  }

  private handle(msg: any): void {
    if (typeof msg.id === "number" && (msg.result !== undefined || msg.error !== undefined)) {
      const p = this.pending.get(msg.id);
      if (!p) {
        return;
      }
      this.pending.delete(msg.id);
      if (msg.error) {
        p.reject(new Error(msg.error.message ?? "알 수 없는 오류"));
      } else {
        p.resolve(msg.result);
      }
      return;
    }
    if (typeof msg.method === "string") {
      this.emit("notification", msg.method, msg.params ?? {});
    }
  }
}
