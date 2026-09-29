from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.core.project_detection import detect_project


class ProjectDetectionTests(unittest.TestCase):
    def test_detects_python_and_safe_commands(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "pyproject.toml").write_text(
                "[project]\nname='demo'\n",
                encoding="utf-8",
            )
            detection = detect_project(path)

            self.assertEqual(detection.primary, "python")
            self.assertIn("python", detection.detected)
            commands = [item.command for item in detection.suggestions]
            self.assertIn("python -m pytest", commands)
            self.assertIn("python -m compileall .", commands)
            self.assertTrue(all(item.safe for item in detection.suggestions))

    def test_detects_node_scripts_and_package_manager(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {
                            "test": "node --test",
                            "build": "vite build",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
            detection = detect_project(path)

            self.assertIn("node", detection.detected)
            commands = [item.command for item in detection.suggestions]
            self.assertIn("pnpm test", commands)
            self.assertIn("pnpm build", commands)

    def test_detects_android_and_never_suggests_publish(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "settings.gradle.kts").write_text(
                'rootProject.name = "demo"\n',
                encoding="utf-8",
            )
            (path / "gradlew").write_text("", encoding="utf-8")
            manifest = path / "app" / "src" / "main"
            manifest.mkdir(parents=True)
            (manifest / "AndroidManifest.xml").write_text(
                "<manifest />",
                encoding="utf-8",
            )

            detection = detect_project(path)

            self.assertEqual(detection.primary, "android")
            commands = [item.command for item in detection.suggestions]
            self.assertIn("./gradlew test", commands)
            self.assertIn("./gradlew assembleDebug", commands)
            serialized = " ".join(commands).lower()
            for unsafe in ("publish", "upload", "release", "sign"):
                self.assertNotIn(unsafe, serialized)

    def test_detects_cmake_and_existing_build_directory(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.20)\n",
                encoding="utf-8",
            )
            (path / "build").mkdir()
            detection = detect_project(path)

            self.assertIn("cmake", detection.detected)
            commands = [item.command for item in detection.suggestions]
            self.assertIn("cmake --build build", commands)
            self.assertIn(
                "ctest --test-dir build --output-on-failure",
                commands,
            )

    def test_mixed_repo_reports_all_supported_types(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "pyproject.toml").write_text("", encoding="utf-8")
            (path / "package.json").write_text(
                '{"scripts":{"test":"node --test"}}',
                encoding="utf-8",
            )
            (path / "CMakeLists.txt").write_text("", encoding="utf-8")
            detection = detect_project(path)

            self.assertEqual(
                detection.detected,
                ("python", "node", "cmake"),
            )
            self.assertEqual(detection.primary, "python")

    def test_gradle_without_android_marker_is_not_misclassified(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "build.gradle").write_text("", encoding="utf-8")
            detection = detect_project(path)
            self.assertNotIn("android", detection.detected)


if __name__ == "__main__":
    unittest.main()
