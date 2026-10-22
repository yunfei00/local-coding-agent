from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandSuggestion:
    purpose: str
    command: str
    reason: str
    windows_command: str | None = None
    safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectDetection:
    primary: str | None
    detected: tuple[str, ...]
    markers: dict[str, tuple[str, ...]]
    suggestions: tuple[CommandSuggestion, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "detected": list(self.detected),
            "markers": {
                key: list(value)
                for key, value in self.markers.items()
            },
            "suggestions": [
                item.to_dict()
                for item in self.suggestions
            ],
        }

    def prompt_text(self) -> str:
        if not self.detected:
            return "Project detection: no supported project type was confidently detected."

        lines = [
            "Project detection: " + ", ".join(self.detected) + ".",
            "Detected markers are hints, not permission to run commands automatically.",
        ]
        if self.primary:
            lines.append("Primary project type: " + self.primary + ".")
        if self.suggestions:
            lines.append("Safe command suggestions:")
            for suggestion in self.suggestions:
                command = suggestion.command
                if suggestion.windows_command:
                    command += " | Windows: " + suggestion.windows_command
                lines.append(
                    f"- {suggestion.purpose}: {command} ({suggestion.reason})"
                )
        lines.append(
            "Do not run publishing, destructive, deployment, signing, release, "
            "or upload commands merely because a project type was detected."
        )
        return "\n".join(lines)


DETECTION_ORDER = ("android", "python", "node", "react", "typescript", "electron", "cmake")


def _existing(root: Path, names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if (root / name).exists())


def _read_package_json(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.is_file() or not path.resolve().is_relative_to(root) or path.stat().st_size > 262144:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _node_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _node_script_command(manager: str, script: str) -> str:
    if manager == "npm":
        return "npm test" if script == "test" else f"npm run {script}"
    return f"{manager} {script}"


def _gradle_commands(root: Path) -> tuple[str, str]:
    if (root / "gradlew").is_file() or (root / "gradlew.bat").is_file():
        return "./gradlew", "gradlew.bat"
    return "gradle", "gradle"


def detect_project(root: str | Path) -> ProjectDetection:
    path = Path(root).expanduser().resolve(strict=False)

    markers: dict[str, tuple[str, ...]] = {}
    markers["python"] = _existing(
        path,
        (
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "pytest.ini",
            "tox.ini",
            "poetry.lock",
            "uv.lock",
        ),
    )
    markers["node"] = _existing(
        path,
        (
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
        ),
    )

    android_markers = list(
        _existing(
            path,
            (
                "settings.gradle",
                "settings.gradle.kts",
                "build.gradle",
                "build.gradle.kts",
                "gradlew",
                "gradlew.bat",
                "gradle.properties",
            ),
        )
    )
    android_manifest_candidates = (
        "app/src/main/AndroidManifest.xml",
        "src/main/AndroidManifest.xml",
    )
    android_markers.extend(
        candidate
        for candidate in android_manifest_candidates
        if (path / candidate).is_file()
    )
    has_android_manifest = any(
        marker.endswith("AndroidManifest.xml")
        for marker in android_markers
    )
    has_android_settings = any(
        marker.startswith("settings.gradle")
        for marker in android_markers
    )
    if not has_android_manifest and not has_android_settings:
        android_markers = []
    markers["android"] = tuple(android_markers)

    markers["cmake"] = _existing(
        path,
        (
            "CMakeLists.txt",
            "CMakePresets.json",
            "CTestConfig.cmake",
        ),
    )
    package = _read_package_json(path)
    dependencies = {}
    for key in ("dependencies", "devDependencies"):
        if isinstance(package.get(key), dict):
            dependencies.update(package[key])
    for kind, packages in (("react", ("react", "react-dom")), ("typescript", ("typescript",)), ("electron", ("electron",))):
        markers[kind] = tuple("package.json:" + dep for dep in packages if dep in dependencies)
    if (path / "tsconfig.json").is_file():
        markers["typescript"] += ("tsconfig.json",)
    tests = path / "tests"
    if not markers["python"] and tests.is_dir() and tests.resolve().is_relative_to(path) and next(tests.glob("test*.py"), None):
        markers["python"] = ("tests/test*.py",)

    detected = tuple(
        kind
        for kind in DETECTION_ORDER
        if markers[kind]
    )
    primary = detected[0] if detected else None
    suggestions: list[CommandSuggestion] = []

    if markers["python"]:
        pyproject = path / "pyproject.toml"
        has_pytest_hint = (path / "pytest.ini").is_file()
        if pyproject.is_file() and pyproject.resolve().is_relative_to(path) and pyproject.stat().st_size <= 262144:
            has_pytest_hint |= "pytest" in pyproject.read_text(encoding="utf-8", errors="replace")
        if has_pytest_hint:
            suggestions.append(
                CommandSuggestion(
                    purpose="test",
                    command="uv run python -m pytest",
                    reason="Python test configuration or pyproject marker detected.",
                )
            )
        elif (path / "tests").is_dir():
            suggestions.append(
                CommandSuggestion(
                    purpose="test",
                    command="uv run python -m unittest discover -s tests -v",
                    reason="Python project with a tests directory detected.",
                )
            )
        suggestions.append(
            CommandSuggestion(
                purpose="check",
                command="uv run python -m compileall .",
                reason="Safe syntax/import bytecode compilation check for Python sources.",
            )
        )

    if markers["node"]:
        package = _read_package_json(path)
        scripts = package.get("scripts")
        scripts = scripts if isinstance(scripts, dict) else {}
        manager = _node_manager(path)
        test_script = str(scripts.get("test") or "").strip()
        if test_script and "no test specified" not in test_script.lower():
            suggestions.append(
                CommandSuggestion(
                    purpose="test",
                    command=_node_script_command(manager, "test"),
                    reason=f"package.json defines a test script; package manager is {manager}.",
                )
            )
        if isinstance(scripts.get("build"), str):
            suggestions.append(
                CommandSuggestion(
                    purpose="build",
                    command=_node_script_command(manager, "build"),
                    reason=f"package.json defines a build script; package manager is {manager}.",
                )
            )
        for name, purpose in (("typecheck", "check"), ("dev", "serve"), ("start", "start")):
            if isinstance(scripts.get(name), str):
                suggestions.append(CommandSuggestion(purpose=purpose, command=_node_script_command(manager, name),
                    reason="Project script hint; use start_process for a long-running server and stop_process after testing.", safe=False))

    if markers["android"]:
        gradle, gradle_windows = _gradle_commands(path)
        suggestions.extend(
            [
                CommandSuggestion(
                    purpose="test",
                    command=f"{gradle} test",
                    windows_command=f"{gradle_windows} test",
                    reason="Android/Gradle project detected.",
                ),
                CommandSuggestion(
                    purpose="build",
                    command=f"{gradle} assembleDebug",
                    windows_command=f"{gradle_windows} assembleDebug",
                    reason="Debug assembly is a local non-publishing Android build.",
                ),
            ]
        )

    if markers["cmake"]:
        build_dir_exists = (path / "build").is_dir()
        if build_dir_exists:
            suggestions.append(
                CommandSuggestion(
                    purpose="build",
                    command="cmake --build build",
                    reason="CMake project with an existing build directory detected.",
                )
            )
            suggestions.append(
                CommandSuggestion(
                    purpose="test",
                    command="ctest --test-dir build --output-on-failure",
                    reason="CMake build directory detected; CTest can run configured tests.",
                )
            )
        else:
            suggestions.append(
                CommandSuggestion(
                    purpose="configure",
                    command="cmake -S . -B build",
                    reason="CMake project detected; configure a local build directory first.",
                )
            )

    return ProjectDetection(
        primary=primary,
        detected=detected,
        markers=markers,
        suggestions=tuple(suggestions),
    )
