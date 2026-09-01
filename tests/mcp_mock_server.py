"""테스트용 최소 MCP stdio 서버.

initialize / notifications/initialized / tools/list / tools/call(echo) 만 처리한다.
"""

import json
import sys


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        mid = msg.get("id")

        if method == "initialize":
            _send({
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "mock"}},
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            _send({
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "입력을 그대로 돌려준다",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                },
            })
        elif method == "tools/call":
            params = msg.get("params", {})
            if params.get("name") == "echo":
                text = params.get("arguments", {}).get("text", "")
                _send({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"echo: {text}"}]},
                })
            else:
                _send({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": "unknown tool"},
                })
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "no method"}})


if __name__ == "__main__":
    main()
