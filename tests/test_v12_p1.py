import tempfile
import unittest
from pathlib import Path
from agent.skills.manager import SkillManager
from agent.skills.router import suggest_skills
from agent.office.engine import create_excel, create_word, create_ppt, inspect_excel, inspect_word, inspect_ppt
from agent.office.edit import edit_excel, edit_word, edit_ppt

class P1Tests(unittest.TestCase):
    def test_skills_routing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            folder=root/".agents"/"skills"/"excel"
            folder.mkdir(parents=True)
            (folder/"SKILL.md").write_text("---\nname: excel\ndescription: Spreadsheet editing\n---\nInstructions",encoding="utf-8")
            manager=SkillManager(root)
            self.assertEqual(suggest_skills(manager,"请编辑 Excel 文件")[0].name,"excel")
            manager.set_enabled("excel",False)
            self.assertEqual(suggest_skills(manager,"编辑 Excel 文件"),[])

    def test_folded_frontmatter(self):
        from agent.skills import _frontmatter
        info = _frontmatter("---\\r\\nname: example\\r\\ndescription: >\\r\\n  A useful skill\\r\\n  for tasks\\r\\n---\\r\\nBody")
        self.assertEqual(info["description"], "A useful skill for tasks")

    def test_excel_edit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.xlsx"
            create_excel(p,{"Data":[["Name","Value"],["A",1]]})
            edit_excel(p,{"sheets":{"Data":{"cells":{"B2":"=2+2"},"styles":{"A1":{"bold":True,"fill":"FF0000"}}}}})
            self.assertEqual(inspect_excel(p)["sheets"][0]["rows"][1][1],"=2+2")

    def test_word_edit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.docx"
            create_word(p,"Report",[{"heading":"Summary","text":"Original text"}])
            edit_word(p,{"replace":[{"find":"Original","with":"Updated"}],"append":["Conclusion"]})
            self.assertIn("Updated text",inspect_word(p)["paragraphs"])
            self.assertIn("Conclusion",inspect_word(p)["paragraphs"])

    def test_ppt_edit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.pptx"
            create_ppt(p,[{"title":"Old","body":"Content"}])
            edit_ppt(p,{"slides":[{"index":0,"title":"New"}],"append":[{"title":"Second","body":"Details"}]})
            slides=inspect_ppt(p)["slides"]
            self.assertEqual(len(slides),2)
            self.assertIn("New",slides[0])

if __name__=="__main__":
    unittest.main()
