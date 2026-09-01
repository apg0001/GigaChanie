"""소스 파일에서 심볼(클래스·함수·상수)을 추출한다.

파이썬은 stdlib `ast`, 그 외 언어는 정규식으로 처리한다(tree-sitter 미사용).
"""

from __future__ import annotations

import ast
import keyword
import re
from dataclasses import dataclass, field

SOURCE_EXTS = {
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".java", ".kt", ".kts",
    ".rb", ".php", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".swift", ".scala",
}

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_PY_KEYWORDS = set(keyword.kwlist) | {"self", "cls", "None", "True", "False"}


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str  # class | func | method | const
    line: int
    signature: str
    parent: str = ""


@dataclass
class FileSymbols:
    symbols: list[Symbol] = field(default_factory=list)
    referenced: set[str] = field(default_factory=set)

    @property
    def def_names(self) -> set[str]:
        return {s.name for s in self.symbols if s.kind in ("class", "func", "method")}


# ------------------------------------------------------------------ Python


def _fmt_args(node: ast.AST) -> str:
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return "()"
    a = node.args
    parts: list[str] = [arg.arg for arg in a.posonlyargs + a.args]
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    parts.extend(arg.arg for arg in a.kwonlyargs)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return "(" + ", ".join(parts) + ")"


def _python_symbols(text: str) -> FileSymbols:
    out = FileSymbols()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _regex_symbols(".py", text)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(_base_name(b) for b in node.bases)
            sig = f"class {node.name}" + (f"({bases})" if bases else "")
            out.symbols.append(Symbol(node.name, "class", node.lineno, sig))
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                    out.symbols.append(
                        Symbol(
                            sub.name,
                            "method",
                            sub.lineno,
                            f"def {sub.name}{_fmt_args(sub)}",
                            parent=node.name,
                        )
                    )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.symbols.append(
                Symbol(node.name, "func", node.lineno, f"def {node.name}{_fmt_args(node)}")
            )
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    out.symbols.append(
                        Symbol(target.id, "const", node.lineno, target.id)
                    )

    for tok in _IDENT_RE.findall(text):
        if tok not in _PY_KEYWORDS:
            out.referenced.add(tok)
    return out


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "…"


# ------------------------------------------------------------------ 정규식 기반

_REGEX_RULES: dict[str, list[tuple[re.Pattern[str], str]]] = {
    "py": [
        (re.compile(r"^\s*class\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"), "func"),
        (re.compile(r"^([A-Z][A-Z0-9_]+)\s*="), "const"),
    ],
    "js": [
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), "func"),
        (re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"), "class"),
        (re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("), "func"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+([A-Z][A-Z0-9_]+)\s*="), "const"),
    ],
    "go": [
        (re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"), "func"),
        (re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)"), "class"),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"), "func"),
        (re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)"), "class"),
    ],
    "jvm": [
        (
            re.compile(
                r"^\s*(?:public|private|protected|internal|open|final|abstract|\s)*"
                r"(?:class|interface|enum|object)\s+([A-Za-z_]\w*)"
            ),
            "class",
        ),
        (
            re.compile(
                r"^\s*(?:public|private|protected|internal|override|suspend|fun|\s)+"
                r"\s+([A-Za-z_]\w*)\s*\("
            ),
            "method",
        ),
    ],
    "ruby": [
        (re.compile(r"^\s*class\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*module\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!]?)"), "func"),
    ],
    "c": [
        (re.compile(r"^[A-Za-z_][\w\s\*]+?\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{?\s*$"), "func"),
        (re.compile(r"^\s*(?:typedef\s+)?(?:struct|enum|union)\s+([A-Za-z_]\w*)"), "class"),
    ],
}

_EXT_TO_RULES = {
    ".py": "py", ".pyi": "py",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
    ".go": "go", ".rs": "rust",
    ".java": "jvm", ".kt": "jvm", ".kts": "jvm", ".scala": "jvm",
    ".rb": "ruby",
    ".c": "c", ".h": "c", ".cpp": "c", ".hpp": "c", ".cc": "c", ".cs": "jvm", ".swift": "jvm",
    ".php": "c",
}


def _regex_symbols(ext: str, text: str) -> FileSymbols:
    out = FileSymbols()
    rules = _REGEX_RULES.get(_EXT_TO_RULES.get(ext, ""), [])
    for i, line in enumerate(text.splitlines(), start=1):
        if len(line) > 400:
            continue
        for pattern, kind in rules:
            m = pattern.match(line)
            if m:
                out.symbols.append(
                    Symbol(m.group(1), kind, i, line.strip()[:110])
                )
                break
    for tok in _IDENT_RE.findall(text):
        out.referenced.add(tok)
    return out


def extract_symbols(ext: str, text: str) -> FileSymbols:
    if ext in (".py", ".pyi"):
        return _python_symbols(text)
    return _regex_symbols(ext, text)
