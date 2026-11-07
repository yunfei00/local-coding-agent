from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from scripts.validation.realworld_benchmark import collect, render
from scripts.validation.realworld_extended import CASES


class RealworldBenchmarkTests(unittest.TestCase):
    def test_catalog_and_external_assertions_reject_untouched_seeds(self):
        self.assertEqual(list(CASES), [f"{number:02d}" for number in range(1, 31)])
        self.assertEqual(len({case.category for case in CASES.values()}), 6)
        for id, case in CASES.items():
            with self.subTest(case=id), tempfile.TemporaryDirectory() as temporary:
                if case.git and not shutil.which("git") or case.language == "node" and not shutil.which("node"):
                    continue  # CI separately provisions Node for the complete fixture test.
                work = Path(temporary)
                case.seed(work)
                self.assertEqual(
                    {path.relative_to(work).as_posix() for path in work.rglob("*")
                     if path.is_file() and ".git" not in path.relative_to(work).parts},
                    set(case.files),
                )
                with self.assertRaises((AssertionError, subprocess.SubprocessError)):
                    case.score(work, {"tools": [], "cancelled_generation": True,
                                     "reconnected": True, "control": case.control})

    def test_scope_does_not_auto_approve_network_or_compound_commands(self):
        case = CASES["15"]
        self.assertFalse(case.approve("run_command", {"command":"git push"}))
        self.assertFalse(case.approve("run_command", {"command":"python -m unittest -q; git push"}))
        self.assertFalse(case.approve("run_command", {"command":"python -m unittest -q","cwd":".."}))
        self.assertFalse(case.approve("desktop_click", {}))
        self.assertTrue(case.approve("run_command", {"command":"git restore feature.txt"}))

    def test_actual_ollama_usage_and_redacted_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            with closing(sqlite3.connect(root / "data" / "local-coding-agent.sqlite3")) as db:
                db.execute("CREATE TABLE runtime_events(sequence INTEGER PRIMARY KEY, kind, metadata_json)")
                db.executemany("INSERT INTO runtime_events(kind, metadata_json) VALUES (?, ?)", [
                    ("request.dispatched", "{}"),
                    ("response.completed", json.dumps({"input_tokens":35, "output_tokens":6, "private":"never_export"})),
                    ("request.settled", json.dumps({"input_tokens":35,"output_tokens":6})),
                ])
                db.commit()
            record = collect(root)
            self.assertEqual(record["model_calls"], 1)
            self.assertEqual(record["tokens"], {"input":35, "output":6, "reported_calls":1})
            self.assertNotIn("never_export", (root / "model-events.json").read_text())
            render(root, {"commit":"base"}, [{"case":"01","repeat":1,"status":"BLOCKED"}], None)
            report = json.loads((root / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(report["counts"], {"BLOCKED":1})


if __name__ == "__main__":
    unittest.main()

