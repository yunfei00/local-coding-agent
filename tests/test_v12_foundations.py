import json
import tempfile
import unittest
from pathlib import Path
from agent.skills.manager import SkillManager
from agent.browser.engine import validate_url

class SkillManagerTests(unittest.TestCase):
    def test_catalog_disable_and_enable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / ".agent" / "skills" / "excel"
            folder.mkdir(parents=True)
            (folder / "skill.json").write_text(json.dumps({"name": "excel", "description": "Spreadsheet"}), encoding="utf-8")
            (folder / "SKILL.md").write_text("Read Excel", encoding="utf-8")
            manager = SkillManager(root)
            self.assertEqual(manager.resolve("excel").name, "excel")
            manager.set_enabled("excel", False)
            self.assertIsNone(manager.resolve("excel"))
            manager.set_enabled("excel", True)
            self.assertIsNotNone(manager.resolve("excel"))

    def test_local_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "skill.json").write_text('{"name":"word","description":"Word documents"}', encoding="utf-8")
            (source / "SKILL.md").write_text("Create docs", encoding="utf-8")
            manager = SkillManager(root)
            self.assertEqual(manager.install_local(source), "word")
            self.assertIsNotNone(manager.resolve("word"))
            manager.uninstall_project("word")
            self.assertIsNone(manager.resolve("word"))

    def test_rejects_url_credentials(self):
        with self.assertRaises(ValueError):
            validate_url("https://user:password@example.com")

if __name__ == "__main__":
    unittest.main()
