from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

from agent.core.version import APP_VERSION, PROTOCOL_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_v010_versions_are_aligned(self) -> None:
        root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        desktop_package = json.loads(
            (ROOT / "desktop" / "package.json").read_text(encoding="utf-8")
        )
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(APP_VERSION, "0.1.0")
        self.assertEqual(root_package["version"], APP_VERSION)
        self.assertEqual(desktop_package["version"], APP_VERSION)
        self.assertEqual(pyproject["project"]["version"], APP_VERSION)
        self.assertEqual(PROTOCOL_VERSION, "phase9")


if __name__ == "__main__":
    unittest.main()
