from __future__ import annotations

import ast
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent.tools.workspace import DEFAULT_IGNORED_DIRS


MAX_INDEX_FILES = 2500
MAX_FILE_BYTES = 512 * 1024
MAX_SYMBOLS_PER_FILE = 24
MAX_TOTAL_SYMBOLS = 1200
MAX_RENDER_CHARS = 24_000

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hpp",
    ".java",
    ".kt",
    ".kts",
}

EXTRA_IGNORED_DIRS = {
    "build",
    "out",
    "target",
    ".gradle",
    ".idea",
    ".next",
    "coverage",
    ".turbo",
}

IMPORTANT_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "package.json",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "CMakeLists.txt",
    "Makefile",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradlew",
    "gradlew.bat",
    "AndroidManifest.xml",
    "README.md",
    "README.rst",
}

ENTRY_NAMES = {
    "main.py",
    "__main__.py",
    "app.py",
    "index.js",
    "index.ts",
    "main.js",
    "main.ts",
    "main.cpp",
    "main.cc",
    "main.c",
    "Main.java",
    "Main.kt",
}


@dataclass(frozen=True)
class RepositorySymbol:
    kind: str
    name: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepositoryFile:
    path: str
    size: int
    mtime_ns: int
    language: str | None
    symbols: list[RepositorySymbol]
    important: bool = False
    entry_point: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "language": self.language,
            "symbols": [item.to_dict() for item in self.symbols],
            "important": self.important,
            "entry_point": self.entry_point,
        }


def _language(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return "typescript" if suffix in {".ts", ".tsx"} else "javascript"
    if suffix in {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp"}:
        return "cpp"
    if suffix == ".java":
        return "java"
    if suffix in {".kt", ".kts"}:
        return "kotlin"
    return None


def _probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(4096)
    except OSError:
        return True


def _python_symbols(text: str) -> list[RepositorySymbol]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    result: list[RepositorySymbol] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append(
                RepositorySymbol("function", node.name, int(node.lineno))
            )
        elif isinstance(node, ast.ClassDef):
            result.append(
                RepositorySymbol("class", node.name, int(node.lineno))
            )
    return result[:MAX_SYMBOLS_PER_FILE]


_JS_PATTERNS = (
    ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*=")),
    ("function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
)

_CPP_PATTERNS = (
    ("class", re.compile(r"^\s*(?:class|struct)\s+([A-Za-z_]\w*)")),
    ("enum", re.compile(r"^\s*enum(?:\s+class)?\s+([A-Za-z_]\w*)")),
    (
        "function",
        re.compile(
            r"^\s*(?:[\w:<>,~*&]+\s+)+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:\{|$)"
        ),
    ),
)

_JAVA_PATTERNS = (
    ("type", re.compile(r"^\s*(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?(?:class|interface|enum|record)\s+([A-Za-z_]\w*)")),
    (
        "method",
        re.compile(
            r"^\s*(?:public|private|protected|static|final|abstract|synchronized|native|default|\s)+[\w<>,?\[\].]+\s+([A-Za-z_]\w*)\s*\("
        ),
    ),
)

_KOTLIN_PATTERNS = (
    ("type", re.compile(r"^\s*(?:data\s+|sealed\s+|open\s+|abstract\s+)?(?:class|interface|object|enum\s+class)\s+([A-Za-z_]\w*)")),
    ("function", re.compile(r"^\s*(?:suspend\s+)?fun\s+(?:<[^>]+>\s*)?([A-Za-z_]\w*)\s*\(")),
)


def _regex_symbols(
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[RepositorySymbol]:
    result: list[RepositorySymbol] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in patterns:
            match = pattern.search(line)
            if match:
                result.append(
                    RepositorySymbol(kind, match.group(1), line_no)
                )
                break
        if len(result) >= MAX_SYMBOLS_PER_FILE:
            break
    return result


def extract_symbols(path: Path, text: str) -> list[RepositorySymbol]:
    language = _language(path)
    if language == "python":
        return _python_symbols(text)
    if language in {"javascript", "typescript"}:
        return _regex_symbols(text, _JS_PATTERNS)
    if language == "cpp":
        return _regex_symbols(text, _CPP_PATTERNS)
    if language == "java":
        return _regex_symbols(text, _JAVA_PATTERNS)
    if language == "kotlin":
        return _regex_symbols(text, _KOTLIN_PATTERNS)
    return []


class RepositoryMap:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.files: dict[str, RepositoryFile] = {}
        self.scanned_files = 0
        self.skipped_files = 0
        self.truncated = False
        self.revision = 0

    @property
    def ignored_dirs(self) -> set[str]:
        return set(DEFAULT_IGNORED_DIRS) | EXTRA_IGNORED_DIRS

    def _ignored(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return True
        return any(part in self.ignored_dirs for part in relative.parts[:-1])

    def _candidate(self, path: Path) -> bool:
        if not path.is_file() or self._ignored(path):
            return False
        return (
            path.suffix.lower() in SOURCE_EXTENSIONS
            or path.name in IMPORTANT_FILES
            or path.name in ENTRY_NAMES
            or "test" in {part.lower() for part in path.parts}
            or "tests" in {part.lower() for part in path.parts}
        )

    def _index_file(self, path: Path) -> RepositoryFile | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        if stat.st_size > MAX_FILE_BYTES or _probably_binary(path):
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        relative = path.relative_to(self.root).as_posix()
        parts_lower = {part.lower() for part in path.parts}
        return RepositoryFile(
            path=relative,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            language=_language(path),
            symbols=extract_symbols(path, text),
            important=path.name in IMPORTANT_FILES,
            entry_point=(
                path.name in ENTRY_NAMES
                or "tests" in parts_lower
                or "test" in parts_lower
            ),
        )

    def build(self) -> None:
        self.files = {}
        self.scanned_files = 0
        self.skipped_files = 0
        self.truncated = False

        candidates: list[Path] = []
        ignored = self.ignored_dirs
        for current_root, dirs, files in os.walk(self.root, topdown=True):
            dirs[:] = sorted(
                [
                    name
                    for name in dirs
                    if name not in ignored
                ],
                key=str.lower,
            )
            base = Path(current_root)
            for name in sorted(files, key=str.lower):
                path = base / name
                if self._candidate(path):
                    candidates.append(path)
                    if len(candidates) >= MAX_INDEX_FILES:
                        self.truncated = True
                        break
            if self.truncated:
                break

        for path in candidates:
            indexed = self._index_file(path)
            if indexed is None:
                self.skipped_files += 1
                continue
            self.files[indexed.path] = indexed
            self.scanned_files += 1
        self.revision += 1

    def refresh_paths(self, paths: list[str] | tuple[str, ...]) -> None:
        changed = False
        for raw in paths:
            try:
                path = (self.root / raw).resolve(strict=False)
                path.relative_to(self.root)
            except (OSError, ValueError):
                continue
            relative = path.relative_to(self.root).as_posix()
            if not path.exists() or not self._candidate(path):
                if relative in self.files:
                    self.files.pop(relative, None)
                    changed = True
                continue
            indexed = self._index_file(path)
            if indexed is None:
                if relative in self.files:
                    self.files.pop(relative, None)
                    changed = True
                continue
            previous = self.files.get(relative)
            if (
                previous is None
                or previous.mtime_ns != indexed.mtime_ns
                or previous.size != indexed.size
            ):
                self.files[relative] = indexed
                changed = True
        if changed:
            self.revision += 1

    def payload(self) -> dict[str, Any]:
        language_counts: dict[str, int] = {}
        symbol_count = 0
        for item in self.files.values():
            if item.language:
                language_counts[item.language] = (
                    language_counts.get(item.language, 0) + 1
                )
            symbol_count += len(item.symbols)
        return {
            "revision": self.revision,
            "file_count": len(self.files),
            "symbol_count": symbol_count,
            "languages": language_counts,
            "truncated": self.truncated,
            "max_files": MAX_INDEX_FILES,
            "max_render_chars": MAX_RENDER_CHARS,
        }

    def file_paths(self, *, limit: int = 500) -> list[str]:
        ranked = sorted(
            self.files.values(),
            key=lambda item: (
                not item.important,
                not item.entry_point,
                item.path.lower(),
            ),
        )
        return [item.path for item in ranked[: max(limit, 0)]]

    def render(self, *, max_chars: int = MAX_RENDER_CHARS) -> str:
        if not self.files:
            return "Repository map: no indexable source/configuration files found."

        lines = [
            "Repository map (deterministic, no embeddings):",
            (
                f"- indexed files: {len(self.files)}"
                f"; revision: {self.revision}"
                f"; truncated: {'yes' if self.truncated else 'no'}"
            ),
        ]

        important = [
            item.path
            for item in self.files.values()
            if item.important
        ]
        if important:
            lines.append("- important files: " + ", ".join(sorted(important)[:80]))

        entries = sorted(
            self.files.values(),
            key=lambda item: (
                not item.important,
                not item.entry_point,
                item.path.lower(),
            ),
        )
        total_symbols = 0
        for item in entries:
            marker = []
            if item.important:
                marker.append("config")
            if item.entry_point:
                marker.append("entry/test")
            suffix = f" [{' / '.join(marker)}]" if marker else ""
            line = f"- {item.path}{suffix}"
            if item.symbols and total_symbols < MAX_TOTAL_SYMBOLS:
                symbols = item.symbols[
                    : min(
                        MAX_SYMBOLS_PER_FILE,
                        MAX_TOTAL_SYMBOLS - total_symbols,
                    )
                ]
                line += " :: " + ", ".join(
                    f"{symbol.kind} {symbol.name}@{symbol.line}"
                    for symbol in symbols
                )
                total_symbols += len(symbols)
            if sum(len(value) + 1 for value in lines) + len(line) > max_chars:
                lines.append("- [repository map truncated]")
                break
            lines.append(line)

        rendered = "\n".join(lines)
        return rendered[:max_chars]
