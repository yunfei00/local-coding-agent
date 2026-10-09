from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.core.context import ContextBudgetManager
from agent.core.explicit_context import (
    extract_file_mentions,
    load_context_file,
)
from agent.core.repository_map import RepositoryMap


class RepositoryMapTests(unittest.TestCase):
    def test_indexes_supported_languages_and_ignores_build_trees(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "src").mkdir()
            (path / "src" / "main.py").write_text(
                "class Demo:\n    pass\n\ndef run():\n    return 1\n",
                encoding="utf-8",
            )
            (path / "src" / "app.ts").write_text(
                "export interface User {}\nexport function load() { return 1; }\n",
                encoding="utf-8",
            )
            (path / "src" / "main.cpp").write_text(
                "class Engine {};\nint run(int argc) { return argc; }\n",
                encoding="utf-8",
            )
            (path / "src" / "Main.java").write_text(
                "public class Main {\n  public void run() {}\n}\n",
                encoding="utf-8",
            )
            (path / "src" / "Main.kt").write_text(
                "class App\nfun run() = 1\n",
                encoding="utf-8",
            )
            (path / "pyproject.toml").write_text(
                "[project]\nname='demo'\n",
                encoding="utf-8",
            )
            (path / "node_modules").mkdir()
            (path / "node_modules" / "skip.py").write_text(
                "def should_not_exist(): pass\n",
                encoding="utf-8",
            )
            (path / "build").mkdir()
            (path / "build" / "generated.cpp").write_text(
                "int generated() { return 0; }\n",
                encoding="utf-8",
            )

            repo_map = RepositoryMap(path)
            repo_map.build()

            indexed = set(repo_map.file_paths(limit=100))
            self.assertIn("src/main.py", indexed)
            self.assertIn("src/app.ts", indexed)
            self.assertIn("src/main.cpp", indexed)
            self.assertIn("src/Main.java", indexed)
            self.assertIn("src/Main.kt", indexed)
            self.assertIn("pyproject.toml", indexed)
            self.assertNotIn("node_modules/skip.py", indexed)
            self.assertNotIn("build/generated.cpp", indexed)

            rendered = repo_map.render()
            self.assertIn("class Demo", rendered)
            self.assertIn("function run", rendered)
            self.assertIn("interface User", rendered)

    def test_incremental_refresh_updates_only_changed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            source = path / "main.py"
            untouched = path / "other.py"
            source.write_text("def old():\n    pass\n", encoding="utf-8")
            untouched.write_text("def stable():\n    pass\n", encoding="utf-8")

            repo_map = RepositoryMap(path)
            repo_map.build()
            revision = repo_map.revision
            stable_before = repo_map.files["other.py"]

            source.write_text(
                "def replacement_name():\n    return 1\n",
                encoding="utf-8",
            )
            repo_map.refresh_paths(["main.py"])

            self.assertGreater(repo_map.revision, revision)
            symbols = [
                item.name
                for item in repo_map.files["main.py"].symbols
            ]
            self.assertEqual(symbols, ["replacement_name"])
            self.assertIs(repo_map.files["other.py"], stable_before)

            source.unlink()
            repo_map.refresh_paths(["main.py"])
            self.assertNotIn("main.py", repo_map.files)

    def test_large_repository_map_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            with patch(
                "agent.core.repository_map.MAX_INDEX_FILES",
                25,
            ):
                for index in range(60):
                    (path / f"module_{index:03}.py").write_text(
                        f"def fn_{index}():\n    return {index}\n",
                        encoding="utf-8",
                    )
                repo_map = RepositoryMap(path)
                repo_map.build()

            self.assertEqual(len(repo_map.files), 25)
            self.assertTrue(repo_map.truncated)
            self.assertLessEqual(len(repo_map.render(max_chars=700)), 700)


class ExplicitContextTests(unittest.TestCase):
    def test_extracts_unique_file_mentions(self) -> None:
        prompt = (
            "Compare @src/app.ts with @src/lib/helper.py and "
            "@src/app.ts, then explain."
        )
        self.assertEqual(
            extract_file_mentions(prompt),
            ["src/app.ts", "src/lib/helper.py"],
        )

    def test_missing_context_file_degrades_to_status(self) -> None:
        from agent.tools.workspace import Workspace

        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            item = load_context_file(
                workspace,
                "missing.py",
                source="pinned_file",
            )
            self.assertEqual(item.status, "missing")
            self.assertIsNone(item.content)

    def test_explicit_context_precedes_history_under_pressure(self) -> None:
        manager = ContextBudgetManager(
            context_window_tokens=2048,
            reserved_output_tokens=512,
        )
        history = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"OLD-{index}-" + ("h" * 700),
            }
            for index in range(20)
        ]
        selection = manager.prepare_initial(
            system_prompt="SYSTEM",
            history=history,
            user_prompt="CURRENT",
            context_blocks=[
                {
                    "source": "mentioned_file",
                    "content": "MENTIONED-CONTENT-" + ("m" * 900),
                },
                {
                    "source": "pinned_file",
                    "content": "PINNED-CONTENT-" + ("p" * 900),
                },
                {
                    "source": "repo_map",
                    "content": "REPO-MAP-" + ("r" * 2400),
                },
            ],
        )
        serialized = str(selection.messages)
        self.assertIn("CURRENT", serialized)
        self.assertIn("MENTIONED-CONTENT", serialized)
        self.assertIn("PINNED-CONTENT", serialized)
        self.assertGreater(
            selection.usage.context_sources.get("mentioned_file", 0),
            0,
        )
        self.assertGreater(
            selection.usage.context_sources.get("pinned_file", 0),
            0,
        )
        self.assertGreater(selection.usage.omitted_history_messages, 0)
        self.assertLessEqual(
            selection.usage.estimated_input_tokens,
            selection.usage.input_budget_tokens,
        )


if __name__ == "__main__":
    unittest.main()
