"""P1 ToolRegistry integration tests without requiring an LLM or desktop."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from agent.tools.workspace import Workspace
from agent.tools.office import OfficeTool
from agent.tools.skills import SkillSuggestTool

class P1ToolTests(unittest.TestCase):
    def test_office_create_edit_verify_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            tool=OfficeTool(Workspace(d))
            async def run():
                created=await tool.execute({"operation":"create","kind":"excel","path":"report.xlsx","spec":{"sheets":{"Data":[["Item","Total"],["A",2]]}}})
                self.assertTrue(created.ok)
                edited=await tool.execute({"operation":"edit","path":"report.xlsx","spec":{"sheets":{"Data":{"cells":{"B2":"=1+2"}}}}})
                self.assertTrue(edited.ok)
                verified=await tool.execute({"operation":"verify","path":"report.xlsx"})
                self.assertTrue(verified.ok)
                bundle=await tool.execute({"operation":"bundle","path":".","name":"deliverable","spec":{
                    "excel":{"sheets":{"Data":[["X"],[1]]}},
                    "word":{"title":"Report","sections":[{"text":"Summary"}]},
                    "ppt":{"slides":[{"title":"Overview","body":"Done"}]}
                }})
                self.assertTrue(bundle.ok)
                self.assertEqual(len(bundle.changed_paths),3)
            asyncio.run(run())

    def test_office_rejects_workspace_escape(self):
        with tempfile.TemporaryDirectory() as d:
            tool=OfficeTool(Workspace(d))
            async def run():
                with self.assertRaises(Exception):
                    await tool.execute({"operation":"create","kind":"excel","path":"../outside.xlsx","spec":{"sheets":{"Data":[[1]]}}})
            asyncio.run(run())

    def test_skills_suggest_tool(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/".agents"/"skills"/"word"
            folder.mkdir(parents=True)
            (folder/"SKILL.md").write_text("---\nname: word\ndescription: Word documents\n---\n",encoding="utf-8")
            tool=SkillSuggestTool(Workspace(d))
            result=asyncio.run(tool.execute({"task":"生成 Word 报告"}))
            self.assertTrue(result.ok)
            self.assertEqual(result.data["skills"][0]["name"],"word")

if __name__=="__main__":
    unittest.main()
