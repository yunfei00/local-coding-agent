from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.tools.diff import parse_unified_diff
from agent.tools.git import GitDiffTool
from agent.tools.workspace import Workspace


RENAME_WITH_SPACE = """diff --git "a/old name.txt" "b/new name.txt"
similarity index 96%
rename from old name.txt
rename to new name.txt
"""


class DiffReviewParserTests(unittest.TestCase):
    def test_parses_rename_similarity_and_paths_with_spaces(self) -> None:
        files = parse_unified_diff(RENAME_WITH_SPACE)

        self.assertEqual(len(files), 1)
        file = files[0]
        self.assertEqual(file["status"], "renamed")
        self.assertEqual(file["old_path"], "old name.txt")
        self.assertEqual(file["new_path"], "new name.txt")
        self.assertEqual(file["path"], "new name.txt")
        self.assertEqual(file["similarity"], 96)
        self.assertEqual(file["hunk_count"], 0)
        self.assertEqual(file["preview_line_count"], 0)

    def test_large_file_preview_is_marked_truncated(self) -> None:
        lines = "\n".join(f"+line-{index}" for index in range(30))
        sample = (
            "diff --git a/demo.txt b/demo.txt\n"
            "--- a/demo.txt\n"
            "+++ b/demo.txt\n"
            "@@ -0,0 +1,30 @@\n"
            + lines
            + "\n"
        )
        files = parse_unified_diff(sample, max_lines_per_file=5)

        self.assertTrue(files[0]["truncated"])
        self.assertEqual(files[0]["additions"], 30)
        self.assertEqual(files[0]["preview_line_count"], 5)


class GitDiffReviewIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_reports_modified_rename_binary_and_large_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "phase16@example.test"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Phase 16"],
                cwd=repo,
                check=True,
            )

            (repo / "normal.txt").write_text("before\n", encoding="utf-8")
            (repo / "rename me.txt").write_text(
                "rename-content\n",
                encoding="utf-8",
            )
            (repo / "blob.bin").write_bytes(b"\x00before")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "initial"],
                cwd=repo,
                check=True,
            )

            (repo / "normal.txt").write_text("after\n", encoding="utf-8")
            (repo / "rename me.txt").rename(repo / "renamed file.txt")
            (repo / "blob.bin").write_bytes(b"\x00after")
            (repo / "large.txt").write_text(
                "\n".join(f"line-{index}" for index in range(600)) + "\n",
                encoding="utf-8",
            )

            result = await GitDiffTool(Workspace(repo)).execute({})

            self.assertTrue(result.ok)
            by_path = {item["path"]: item for item in result.data["files"]}

            self.assertEqual(by_path["normal.txt"]["status"], "modified")
            self.assertEqual(by_path["rename me.txt"]["status"], "deleted")
            self.assertEqual(by_path["renamed file.txt"]["status"], "untracked")
            self.assertTrue(by_path["blob.bin"]["binary"])
            self.assertTrue(by_path["large.txt"]["truncated"])

            review = result.data["review"]
            self.assertTrue(review["read_only"])
            self.assertEqual(review["mode"], "working_tree")
            self.assertFalse(review["complete_preview"])
            self.assertIn("blob.bin", review["binary_files"])
            self.assertIn("large.txt", review["truncated_files"])
            self.assertEqual(review["renamed_files"], [])
            self.assertGreaterEqual(review["status_counts"]["modified"], 2)
            self.assertEqual(review["status_counts"]["deleted"], 1)
            self.assertEqual(review["status_counts"]["untracked"], 2)

            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            staged = await GitDiffTool(Workspace(repo)).execute(
                {"staged": True}
            )
            staged_by_path = {
                item["path"]: item
                for item in staged.data["files"]
            }

            self.assertEqual(
                staged_by_path["renamed file.txt"]["status"],
                "renamed",
            )
            self.assertEqual(
                staged_by_path["renamed file.txt"]["old_path"],
                "rename me.txt",
            )
            self.assertEqual(
                staged_by_path["renamed file.txt"]["similarity"],
                100,
            )
            staged_review = staged.data["review"]
            self.assertEqual(staged_review["mode"], "staged")
            self.assertEqual(
                staged_review["renamed_files"][0]["old_path"],
                "rename me.txt",
            )
            self.assertEqual(
                staged_review["status_counts"]["renamed"],
                1,
            )

    async def test_empty_diff_has_complete_read_only_review(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            result = await GitDiffTool(Workspace(repo)).execute({})

            self.assertTrue(result.ok)
            self.assertEqual(result.data["files"], [])
            self.assertTrue(result.data["review"]["read_only"])
            self.assertTrue(result.data["review"]["complete_preview"])


if __name__ == "__main__":
    unittest.main()
