"""`giga serve` - 에디터/GUI 용 stdio JSON-RPC 브리지를 실행한다."""

from __future__ import annotations

import sys

import typer


def serve() -> None:
    """stdin/stdout 으로 JSON-RPC 를 주고받는 브리지를 실행한다.

    VS Code 확장 등이 이 프로세스를 자식으로 띄워 세션을 만들고 프롬프트를
    보낸다. stdout 에는 JSON-RPC 만 출력되고, 로그는 stderr 로 나간다.
    """
    from gigachanie._stdio import force_utf8_stdio
    from gigachanie.serve.server import RpcServer

    force_utf8_stdio()
    try:
        RpcServer().serve_forever()
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None
    sys.exit(0)
