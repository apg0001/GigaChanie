"""GigaChanie CLI 진입점.

각 하위 명령은 별도 모듈에서 구현하고 이 파일에서 등록만 한다.
"""

from __future__ import annotations

import typer
from rich.console import Console

from gigachanie import __version__

app = typer.Typer(
    name="giga",
    help="오픈 웨이트 LLM으로 동작하는 코딩 에이전트.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


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


@app.command()
def hello() -> None:
    """설치가 정상인지 확인하는 임시 명령. (이후 제거 예정)"""
    console.print("[bold green]GigaChanie 준비 완료[/bold green]")
    console.print("`giga --help` 로 명령을 확인하세요.")


if __name__ == "__main__":
    app()
