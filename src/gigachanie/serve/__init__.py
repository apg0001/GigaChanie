"""`giga serve` - 에디터/GUI 가 붙는 stdio JSON-RPC 브리지."""

from gigachanie.serve.server import PROTOCOL_VERSION, RpcServer

__all__ = ["PROTOCOL_VERSION", "RpcServer"]
