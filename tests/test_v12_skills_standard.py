import json
import tempfile
import unittest
from pathlib import Path
from agent.skills import discover_skills
from agent.skills.manager import SkillManager

class StandardSkillsTests(unittest.TestCase):
    def test_frontmatter_without_json(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/".agents"/"skills"/"excel"
            folder.mkdir(parents=True)
            (folder/"SKILL.md").write_text("---\nname: excel\ndescription: Read spreadsheets\n---\nInstructions",encoding="utf-8")
            self.assertEqual(discover_skills(d)[0].name,"excel")
            manager=SkillManager(d)
            self.assertEqual(manager.instructions("excel").splitlines()[-1],"Instructions")

    def test_zip_install_and_assets(self):
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            z=root/"skill.zip"
            with zipfile.ZipFile(z,"w") as f:
                f.writestr("demo/SKILL.md","---\nname: demo\ndescription: Demo\n---\nHello")
                f.writestr("demo/assets/sample.txt","sample")
            manager=SkillManager(root)
            self.assertEqual(manager.install_local(z),"demo")
            self.assertTrue((root/".agent"/"skills"/"demo"/"assets"/"sample.txt").exists())

    def test_zip_traversal_rejected(self):
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            z=root/"bad.zip"
            with zipfile.ZipFile(z,"w") as f:
                f.writestr("../outside","bad")
            with self.assertRaises(ValueError):
                SkillManager(root).install_local(z)

if __name__=="__main__":
    unittest.main()
