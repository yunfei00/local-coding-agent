from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

from agent.core.version import APP_VERSION, PROTOCOL_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_versions_are_aligned(self) -> None:
        root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        desktop_package = json.loads(
            (ROOT / "desktop" / "package.json").read_text(encoding="utf-8")
        )
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(root_package["version"], APP_VERSION)
        self.assertEqual(desktop_package["version"], APP_VERSION)
        self.assertEqual(pyproject["project"]["version"], APP_VERSION)
        self.assertEqual(PROTOCOL_VERSION, "1.0.0")

        desktop_protocol = (
            ROOT / "desktop" / "electron" / "protocol.ts"
        ).read_text(encoding="utf-8")
        self.assertIn(
            f'DESKTOP_PROTOCOL_VERSION = "{PROTOCOL_VERSION}"',
            desktop_protocol,
        )
        self.assertNotIn("phase9", desktop_protocol.lower())

    def test_vite_uses_relative_assets_for_packaged_file_protocol(self) -> None:
        vite_config = (ROOT / "desktop" / "vite.config.ts").read_text(encoding="utf-8")
        self.assertIn('base: "./"', vite_config)


if __name__ == "__main__":
    unittest.main()
