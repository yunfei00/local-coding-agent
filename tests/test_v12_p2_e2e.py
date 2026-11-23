"""Optional real Chromium smoke test. Uses only an in-process local fixture."""
import asyncio
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import importlib.util
import threading
import unittest
from unittest.mock import patch

class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body=b'<html><title>Browser P2 Fixture</title><body><h1 id="status">Ready</h1><input id="name"><button id="go" onclick="document.querySelector(\'#status\').textContent=document.querySelector(\'#name\').value">Apply</button><table><tr><td>OK</td></tr></table></body></html>'
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args):
        pass

@unittest.skipUnless(importlib.util.find_spec("playwright"),"Playwright is not installed")
class BrowserRealChromiumTests(unittest.TestCase):
    def test_real_browser_dom_fill_click_tables_and_screenshot(self):
        from agent.browser.sessions import BrowserSessions,browser_diagnostics
        if not browser_diagnostics()["chromium_installed"]:
            self.skipTest("Chromium browser binary is not installed")
        server=ThreadingHTTPServer(("127.0.0.1",0),Fixture)
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        url=f"http://127.0.0.1:{server.server_port}/"
        async def run():
            sessions=BrowserSessions()
            try:
                opened=await sessions.open(url)
                sid=opened["session_id"]
                self.assertEqual(opened["title"],"Browser P2 Fixture")
                await sessions.action(sid,"fill",selector="#name",value="P2 passed")
                result=await sessions.action(sid,"click",selector="#go")
                self.assertIn("P2 passed",result["text"])
                tables=await sessions.action(sid,"tables")
                self.assertEqual(tables["tables"][0][0][0],"OK")
                self.assertTrue((await sessions.close(sid))["closed"])
            finally:
                await sessions.close_all()
        try:
            # The local fixture is allowed only inside this test; production
            # continues to reject loopback and private addresses.
            with patch("agent.browser.sessions.validate_url",lambda value:value):
                asyncio.run(run())
        finally:
            server.shutdown()
            server.server_close()

if __name__=="__main__":
    unittest.main()
