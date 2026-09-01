"""GigaChanie CLI 진입점.

각 하위 명령은 `gigachanie.commands` 하위 모듈에서 구현하고 여기서 등록만 한다.
"""

from __future__ import annotations

import typer
from rich.console import Console

from gigachanie import __version__
from gigachanie.commands import agent as agent_cmd
from gigachanie.commands import ask as ask_cmd
from gigachanie.commands import chat as chat_cmd
from gigachanie.commands import doctor as doctor_cmd
from gigachanie.commands import init as init_cmd
from gigachanie.commands import map as map_cmd
from gigachanie.commands import memory as memory_cmd
from gigachanie.commands import model as model_cmd

app = typer.Typer(
    name="giga",
    help="오픈 웨이트 LLM으로 동작하는 코딩 에이전트.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

app.command("doctor")(doctor_cmd.doctor)
app.command("ask")(ask_cmd.ask)
app.command("ping")(ask_cmd.ping)
app.command("agent")(agent_cmd.agent)
app.command("chat")(chat_cmd.chat)
app.command("init")(init_cmd.init)
app.command("map")(map_cmd.repo_map_cmd)
app.add_typer(memory_cmd.app, name="memory")
app.add_typer(model_cmd.app, name="model")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"GigaChanie {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="버전을 출력하고 종료한다.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """GigaChanie - 로컬/오픈모델 기반 코딩 에이전트."""


if __name__ == "__main__":
    app()
