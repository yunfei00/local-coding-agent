import json
import tempfile
import unittest
from pathlib import Path

from agent.skills import discover_skills


class SkillDiscoveryTests(unittest.TestCase):
    def test_discovers_valid_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / ".agent" / "skills" / "excel"
            folder.mkdir(parents=True)
            (folder / "skill.json").write_text(json.dumps({"name": "excel", "description": "Read workbooks"}), encoding="utf-8")
            (folder / "SKILL.md").write_text("Instructions", encoding="utf-8")
            found = discover_skills(temp)
            self.assertEqual([s.name for s in found], ["excel"])
            self.assertEqual(found[0].instructions, "Instructions")

    def test_rejects_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / ".agent" / "skills" / "excel"
            folder.mkdir(parents=True)
            (folder / "skill.json").write_text('{"name":"other","description":"x"}', encoding="utf-8")
            (folder / "SKILL.md").write_text("Instructions", encoding="utf-8")
            self.assertEqual(discover_skills(temp), [])

    def test_missing_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(discover_skills(temp), [])


if __name__ == "__main__":
    unittest.main()
