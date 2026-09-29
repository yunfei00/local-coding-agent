from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.tools.base import ToolError
from agent.tools.filesystem import SearchFilesTool
from agent.tools.workspace import Workspace


class SearchFilesV2Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "src").mkdir()
        (root / "generated").mkdir()

        (root / "src" / "demo.py").write_text(
            "alpha\n"
            "target = 42\n"
            "omega\n",
            encoding="utf-8",
        )
        (root / "src" / "other.py").write_text(
            "TARGET = 7\n"
            "tail\n",
            encoding="utf-8",
        )
        (root / "src" / "ignored.py").write_text(
            "target = 99\n",
            encoding="utf-8",
        )
        (root / "generated" / "skip.py").write_text(
            "target = 123\n",
            encoding="utf-8",
        )
        self.tool = SearchFilesTool(Workspace(root))

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_regex_glob_exclude_and_context(self) -> None:
        result = await self.tool.execute(
            {
                "query": r"target\s*=\s*\d+",
                "regex": True,
                "glob": "src/*.py",
                "exclude": ["src/ignored.py"],
                "context_before": 1,
                "context_after": 1,
                "max_results": 20,
            }
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.data["mode"], "regex")
        paths = [item["path"].replace("\\", "/") for item in result.data["results"]]
        self.assertEqual(paths, ["src/demo.py", "src/other.py"])

        first = result.data["results"][0]
        self.assertEqual(first["line"], 2)
        self.assertEqual(first["before"], [{"line": 1, "text": "alpha"}])
        self.assertEqual(first["after"], [{"line": 3, "text": "omega"}])

    async def test_literal_search_remains_case_insensitive_by_default(self) -> None:
        result = await self.tool.execute(
            {
                "query": "target = 7",
                "glob": "*.py",
            }
        )
        self.assertEqual(len(result.data["results"]), 1)
        self.assertTrue(
            result.data["results"][0]["path"].replace("\\", "/").endswith(
                "src/other.py"
            )
        )

    async def test_custom_exclude_skips_generated_tree(self) -> None:
        result = await self.tool.execute(
            {
                "query": "target",
                "glob": "*.py",
                "exclude": ["generated/**", "src/ignored.py"],
            }
        )
        paths = {
            item["path"].replace("\\", "/")
            for item in result.data["results"]
        }
        self.assertEqual(paths, {"src/demo.py", "src/other.py"})

    async def test_result_limit_sets_truncated(self) -> None:
        result = await self.tool.execute(
            {
                "query": "target",
                "glob": "*.py",
                "max_results": 1,
            }
        )
        self.assertEqual(len(result.data["results"]), 1)
        self.assertTrue(result.data["truncated"])

    async def test_invalid_regex_is_rejected(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            await self.tool.execute(
                {
                    "query": "[unterminated",
                    "regex": True,
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_REGEX")

    async def test_invalid_exclude_type_is_rejected(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            await self.tool.execute(
                {
                    "query": "target",
                    "exclude": "*.tmp",
                }
            )
        self.assertEqual(ctx.exception.code, "INVALID_EXCLUDE")


if __name__ == "__main__":
    unittest.main()
