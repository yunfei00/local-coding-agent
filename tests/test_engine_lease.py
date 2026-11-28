import asyncio
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.core.engine_lease import EngineLeaseOccupied, engine_lease


class EngineLeaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_cross_process_exclusion(self):
        script = (
            "import sys; from agent.core.engine_lease import engine_lease\n"
            "with engine_lease(sys.argv[1]): print('acquired')\n"
        )
        args = [sys.executable, "-c", script, str(self.root)]
        with engine_lease(self.root):
            result = subprocess.run(args, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Engine execution lease occupied", result.stderr)
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("acquired", result.stdout)

    def test_exception_releases_lease(self):
        with self.assertRaises(ValueError):
            with engine_lease(self.root):
                raise ValueError("execution failure")
        with engine_lease(self.root):
            pass

    def test_orphan_is_not_reclaimed(self):
        (self.root / "engine-execution.lock").mkdir()
        with self.assertRaisesRegex(EngineLeaseOccupied, "lease occupied"):
            with engine_lease(self.root):
                self.fail("orphan lease must not be reclaimed")

    def test_background_contention_pauses_without_execution(self):
        from agent.core.background import BackgroundJobs

        async def scenario():
            db = sqlite3.connect(":memory:")
            try:
                jobs = BackgroundJobs(db)
                jobs.add("job", "thread", "project")
                called = False

                async def operation():
                    nonlocal called
                    called = True

                with engine_lease(self.root):
                    with self.assertRaises(EngineLeaseOccupied):
                        await jobs.run("job", operation)
                self.assertFalse(called)
                self.assertEqual(jobs.list()[0]["state"], "paused")
                self.assertFalse(jobs.running_claims)
                jobs.add("next", "thread", "project")
                await jobs.run("next", operation)
                self.assertTrue(called)
                self.assertFalse(jobs.running_claims)
            finally:
                db.close()

        with patch.dict(os.environ, {"LCA_DATA_DIR": str(self.root)}):
            asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
