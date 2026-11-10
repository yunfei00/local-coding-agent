import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from agent.browser.engine import validate_url
from agent.browser.sessions import BrowserSessions
from agent.tools.browser import BrowserSessionTool
from agent.tools.workspace import Workspace

class BrowserP2Tests(unittest.TestCase):
    def test_blocks_local_and_credentials(self):
        for url in ["file:///etc/passwd","http://127.0.0.1/","http://localhost/","http://user:pass@example.com/","ftp://example.com"]:
            with self.subTest(url=url),self.assertRaises((ValueError,OSError)):
                validate_url(url)

    def test_unknown_session(self):
        sessions=BrowserSessions()
        with self.assertRaises(ValueError):
            sessions._get("missing")

    def test_browser_tool_schema(self):
        with tempfile.TemporaryDirectory() as d:
            tool=BrowserSessionTool(BrowserSessions(),Workspace(d))
            schema=tool.ollama_schema()["function"]["parameters"]
            self.assertIn("screenshot",schema["properties"]["operation"]["enum"])
            self.assertIn("click",schema["properties"]["operation"]["enum"])

    def test_screenshot_rejects_outside_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            tool=BrowserSessionTool(BrowserSessions(),Workspace(d))
            async def run():
                with self.assertRaises(Exception):
                    await tool.execute({"operation":"screenshot","session_id":"test","path":"../escape.png"})
            asyncio.run(run())

    def test_workflow_stops_on_failure(self):
        sessions=BrowserSessions()
        async def fake_action(session_id,operation,**kwargs):
            if operation=="click":
                raise ValueError("Element not found")
            return {"url":"https://example.com"}
        sessions.action=fake_action
        result=asyncio.run(sessions.workflow("fake",[
            {"operation":"wait"},{"operation":"click","selector":"#missing"},{"operation":"wait"}]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"],1)
        self.assertEqual(len(result["history"]),2)

    def test_browser_session_action_requires_unique_selector(self):
        class FakePage:
            locator=lambda self,selector:FakeLocator()
        class FakeLocator:
            count=AsyncMock(return_value=2)
        sessions=BrowserSessions()
        sessions._sessions["fake"]=type("Session",(),{"page":FakePage()})()
        async def run():
            with self.assertRaisesRegex(ValueError,"exactly one"):
                await sessions.action("fake","click",selector="button")
        asyncio.run(run())

if __name__=="__main__":
    unittest.main()
