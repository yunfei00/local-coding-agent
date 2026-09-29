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


DETECTION_ORDER = ("android", "python", "node", "cmake")


def _existing(root: Path, names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if (root / name).exists())


def _read_package_json(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.is_file():
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

    detected = tuple(
        kind
        for kind in DETECTION_ORDER
        if markers[kind]
    )
    primary = detected[0] if detected else None
    suggestions: list[CommandSuggestion] = []

    if markers["python"]:
        has_pytest_hint = any(
            marker in {"pytest.ini", "tox.ini", "pyproject.toml"}
            for marker in markers["python"]
        )
        if has_pytest_hint:
            suggestions.append(
                CommandSuggestion(
                    purpose="test",
                    command="python -m pytest",
                    reason="Python test configuration or pyproject marker detected.",
                )
            )
        elif (path / "tests").is_dir():
            suggestions.append(
                CommandSuggestion(
                    purpose="test",
                    command="python -m unittest discover",
                    reason="Python project with a tests directory detected.",
                )
            )
        suggestions.append(
            CommandSuggestion(
                purpose="check",
                command="python -m compileall .",
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
