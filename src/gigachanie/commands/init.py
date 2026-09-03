"""`giga init` - 리포를 훑어 AGENTS.md 초안을 만든다."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

import typer

from gigachanie.ui import make_console

console = make_console()

_LANG_EXT = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".swift": "Swift",
}
_IGNORE = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    "target", ".next", ".nuxt", "vendor", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", "coverage", ".agent",
}


def _run(args: list[str], cwd: Path) -> str | None:
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _language_mix(root: Path) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in _IGNORE for part in p.relative_to(root).parts):
            continue
        lang = _LANG_EXT.get(p.suffix)
        if lang:
            counter[lang] += 1
    return counter.most_common(4)


def _detect_commands(root: Path) -> dict[str, list[str]]:
    build: list[str] = []
    test: list[str] = []
    lint: list[str] = []
    run: list[str] = []

    if (root / "pyproject.toml").is_file():
        txt = (root / "pyproject.toml").read_text("utf-8", errors="replace")
        if "pytest" in txt:
            test.append("python -m pytest")
        if "[tool.ruff]" in txt or "ruff" in txt:
            lint.append("ruff check .")
        if "mypy" in txt:
            lint.append("mypy")
        build.append("python -m pip install -e .")
    if (root / "package.json").is_file():
        try:
            pkg = json.loads((root / "package.json").read_text("utf-8", errors="replace"))
            scripts = pkg.get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        npm_map = {
            "build": build,
            "test": test,
            "lint": lint,
            "dev": run,
            "start": run,
        }
        for key, bucket in npm_map.items():
            if key in scripts:
                bucket.append(f"npm run {key}")
    if (root / "Cargo.toml").is_file():
        build.append("cargo build")
        test.append("cargo test")
        lint.append("cargo clippy")
    if (root / "go.mod").is_file():
        build.append("go build ./...")
        test.append("go test ./...")
    if (root / "Makefile").is_file():
        mk = (root / "Makefile").read_text("utf-8", errors="replace")
        targets = {
            ln.split(":")[0].strip()
            for ln in mk.splitlines()
            if ":" in ln and not ln[:1].isspace()
        }
        mk_map = {"build": build, "test": test, "lint": lint, "run": run}
        for t, bucket in mk_map.items():
            if t in targets:
                bucket.append(f"make {t}")

    return {"build": build, "test": test, "lint": lint, "run": run}


def _project_name(root: Path) -> str:
    readme = next(
        (root / n for n in ("README.md", "README.rst", "readme.md") if (root / n).is_file()),
        None,
    )
    if readme:
        for line in readme.read_text("utf-8", errors="replace").splitlines():
            s = line.lstrip("# ").strip()
            if s:
                return s
    return root.name


def _render(root: Path) -> str:
    name = _project_name(root)
    langs = _language_mix(root)
    cmds = _detect_commands(root)
    remote = _run(["git", "remote", "get-url", "origin"], root)
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)

    top_dirs = sorted(
        d.name for d in root.iterdir() if d.is_dir() and d.name not in _IGNORE
    )[:12]

    lang_line = ", ".join(f"{name}({n})" for name, n in langs) or "(감지 안 됨)"

    def block(items: list[str]) -> str:
        return "\n".join(f"- `{c}`" for c in dict.fromkeys(items)) or "- (확인 필요)"

    lines = [
        f"# {name}",
        "",
        "> 이 파일은 `giga init` 이 생성한 초안입니다. 직접 다듬어 주세요.",
        "> GigaChanie 에이전트가 매 세션 이 내용을 읽습니다.",
        "",
        "## 프로젝트 개요",
        "",
        f"- 주요 언어: {lang_line}",
    ]
    if remote:
        lines.append(f"- 저장소: {remote}")
    if branch:
        lines.append(f"- 기본 브랜치: {branch}")
    lines += [
        "- (한두 문장으로 이 프로젝트가 무엇인지 설명하세요)",
        "",
        "## 빌드 · 실행",
        "",
        block(cmds["build"] + cmds["run"]),
        "",
        "## 테스트",
        "",
        block(cmds["test"]),
        "",
        "## 린트 · 타입체크",
        "",
        block(cmds["lint"]),
        "",
        "## 디렉터리",
        "",
        "\n".join(f"- `{d}/`" for d in top_dirs) or "- (없음)",
        "",
        "## 코드 컨벤션",
        "",
        "- (명명 규칙, 포매터, 주석 언어 등)",
        "",
        "## 주의사항",
        "",
        "- (건드리면 안 되는 파일, 배포 전 확인할 것 등)",
        "",
    ]
    return "\n".join(lines)


def init(
    root: Path = typer.Option(Path("."), "--root", "-C", help="대상 디렉터리."),
    force: bool = typer.Option(False, "--force", "-f", help="기존 AGENTS.md 를 덮어쓴다."),
    show: bool = typer.Option(False, "--show", help="파일로 쓰지 않고 출력만 한다."),
) -> None:
    """리포를 분석해 AGENTS.md 초안을 생성한다."""
    root = root.resolve()
    if not root.is_dir():
        console.print(f"[red]디렉터리가 아닙니다: {root}[/red]")
        raise typer.Exit(code=1)

    target = root / "AGENTS.md"
    if target.exists() and not force and not show:
        console.print(
            f"[yellow]{target.name} 가 이미 있습니다.[/yellow] "
            "덮어쓰려면 --force, 미리보려면 --show."
        )
        raise typer.Exit(code=1)

    content = _render(root)
    if show:
        console.print(content)
        return

    target.write_text(content, encoding="utf-8")
    console.print(f"[green]생성됨:[/green] {target}")
    console.print("[dim]내용을 검토하고 프로젝트에 맞게 수정하세요.[/dim]")
