/* Real Electron/Renderer/Agent smoke with an isolated local provider and data. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");
const net = require("node:net");
const { execFileSync, spawn } = require("node:child_process");
const { _electron } = require("../../desktop/node_modules/playwright-core");

const root = path.resolve(__dirname, "../..");
const reportDir = path.join(root, "validation-reports");
fs.mkdirSync(reportDir, {recursive: true});
const data = fs.mkdtempSync(path.join(os.tmpdir(), "lca-ui-"));
const project = path.join(data, "calculator-project");
fs.mkdirSync(project);
fs.writeFileSync(path.join(project, "README.md"), "# Calculator\nLocal smoke fixture\n");
execFileSync("git", ["init", "-q", "-b", "main"], {cwd: project});
fs.writeFileSync(path.join(project, "calculator.py"), "def add(a,b):\n    return a - b\n");
fs.writeFileSync(path.join(project, ".gitignore"), "__pycache__/\n.venv/\n");
fs.mkdirSync(path.join(project, "tests"));
fs.writeFileSync(path.join(project, "tests/test_calc.py"), "import unittest\nfrom calculator import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n");
for (const args of [["config","user.name","Smoke"],["config","user.email","smoke@example.test"],["add","."],["commit","-qm","fixture"]]) execFileSync("git", args, {cwd:project});
let rejectModels = false;
let protectedCredentialSeen = false;
let mcpProcess;
let blockPlanning = false;
let planningRequests = 0;
const modelRequests = [];
const checks = [];
const skipped = [];
const errors = [];
const provider = http.createServer((req, res) => {
  if (req.url === "/api/tags") {res.writeHead(200, {"Content-Type":"application/json"}); return res.end(JSON.stringify({models:[{name:"gpt-oss:20b"},{name:"task-executor"}]}));}
  if (req.url.endsWith("/models")) {
    if (req.headers.authorization === "Bearer mock-only-not-a-real-key") protectedCredentialSeen = true;
    res.writeHead(rejectModels ? 503 : 200, {"Content-Type": "application/json"});
    return res.end(JSON.stringify(rejectModels ? {error: {message: "Intentional startup failure"}} : {data: [{id: "smoke-coder"},{id:"DeepSeek-V4-Flash-SaaS"}]}));
  }
  let body = "";
  req.on("data", chunk => body += chunk);
  req.on("end", () => {
    const payload = JSON.parse(body || "{}");
    if (req.url.endsWith("/chat") || req.url.endsWith("/chat/completions")) modelRequests.push({url:req.url,model:payload.model});
    if (req.url === "/api/show") {res.writeHead(200, {"Content-Type":"application/json"}); return res.end(JSON.stringify({capabilities:["tools"]}));}
    if (req.url === "/api/chat") {
      if (payload.model === "task-planner" && blockPlanning) {
        planningRequests++;
        res.writeHead(200, {"Content-Type":"application/x-ndjson"});
        res.write(JSON.stringify({message:{content:""},done:false}) + "\n");
        return;
      }
      let message = {content:"Task implementation complete"};
      if (payload.model === "gpt-oss:20b") message.content = "Selected local model received the chat.";
      else if (payload.model === "task-planner") message.content = JSON.stringify({steps:[{description:"Fix calculator using actual tools"}]});
      else if (payload.model === "task-reviewer") message.content = "Tests passed; review isolated Diff before Git actions.";
      else if (!payload.messages.some(m => m.role === "tool" && (m.name === "apply_patch" || m.tool_name === "apply_patch"))) message = {content:"", tool_calls:[{function:{name:"apply_patch", arguments:{path:"calculator.py", old_text:"return a - b", new_text:"return a + b"}}}]};
      res.writeHead(200, {"Content-Type":"application/x-ndjson"});
      return res.end(JSON.stringify({message, done:true, prompt_eval_count:120, eval_count:30}) + "\n");
    }
    const first = payload.messages?.[0]?.content;
    const syntheticProbe = Array.isArray(first) && first[0]?.text?.includes("Read the image as data");
    if (first === "Reply with LCA_OK only." || syntheticProbe || payload.tools?.some(t => t.function.name === "lca_diagnostic_echo")) {
      let message = {content:"LCA_OK"};
      if (syntheticProbe) {
        const image = Buffer.from(first[1].image_url.url.split(",")[1], "base64");
        assert.equal(image.subarray(0,2).toString("hex"), "ffd8");
        // Deliberately cannot recognize the hidden random check. HTTP 200 must FAIL vision.
        message.content = JSON.stringify({title:"LCA Vision Test",button_color:"blue",button_text:"Settings",input_boxes:1,check_text:"CHECK-WRONG"});
      }
      if (payload.tools) message = {content:null,tool_calls:[{id:"diagnostic",type:"function",function:{name:"lca_diagnostic_echo",arguments:'{"value":"LCA_OK"}'}}]};
      res.writeHead(200, {"Content-Type":"application/json"});
      return res.end(JSON.stringify({choices:[{message,finish_reason:payload.tools ? "tool_calls" : "stop"}],usage:{prompt_tokens:12,completion_tokens:8}}));
    }
    const prompt = payload.messages?.filter(m => m.role === "user").at(-1)?.content ?? "";
    for (const message of payload.messages ?? []) for (const item of message.tool_calls ?? []) assert.equal(typeof item.function.arguments, "string", "OpenAI wire tool arguments must be JSON strings");
    res.writeHead(200, {"Content-Type": "text/event-stream"});
    if (payload.model === "api-reviewer") {
      let delta = {content:"Review verified tests and Diff."};
      if (prompt.includes("M1 Single Agent")) {
        const results = payload.messages.filter(m => m.role === "tool");
        const seen = name => results.filter(m => m.name === name);
        let name, args;
        if (!seen("read_file").length) {name="read_file"; args={path:"calculator.py"};}
        else if (!seen("run_command").length) {name="run_command"; args={command:"uv run --no-project python -m unittest discover -s tests -v"};}
        else if (!seen("apply_patch").length) {name="apply_patch"; args={path:"calculator.py",old_text:"return a - b",new_text:"return a + b  # M1 fix"};}
        else if (seen("run_command").length < 2) {name="run_command"; args={command:"uv run --no-project python -m unittest discover -s tests -v"};}
        else if (!seen("git_diff").length) {name="git_diff"; args={};}
        if (name) delta={tool_calls:[{index:0,id:`m1-call-${results.length}`,type:"function",function:{name,arguments:JSON.stringify(args)}}]};
        else delta={content:"M1 Single Agent repaired calculator after actual failing tests, reran tests and inspected Diff."};
      }
      else if (payload.tools?.some(t => t.function.name === "submit_plan")) delta = {content:JSON.stringify({steps:[{description:"Fix calculator addition and run independent tests"}]})};
      else if (payload.tools?.some(t => t.function.name === "apply_patch")) {
        if (!payload.messages.some(m => m.role === "tool")) delta = {tool_calls:[{index:0,id:"api-patch",type:"function",function:{name:"apply_patch",arguments:JSON.stringify({path:"calculator.py",old_text:"return a - b",new_text:"return a + b"})}}]};
        else delta = {content:"Calculator implementation complete."};
      }
      res.write("data: " + JSON.stringify({choices:[{delta,finish_reason:delta.tool_calls ? "tool_calls" : "stop"}],usage:{prompt_tokens:100,completion_tokens:20}}) + "\n\n");
      return res.end("data: [DONE]\n\n");
    }
    const send = (text, finish = null) => res.write("data: " + JSON.stringify({choices: [{index: 0, delta: {content: text}, finish_reason: finish}]}) + "\n\n");
    if (prompt.includes("invalid-json-smoke")) {
      const repairing = payload.messages.some(m => m.role === "system" && String(m.content).includes("Runtime protocol feedback"));
      if (!repairing) {
        res.write("data: " + JSON.stringify({choices:[{delta:{content:"DISCARD_PARTIAL_🙂",tool_calls:[{index:0,id:"invalid",type:"function",function:{name:"write_file",arguments:'{"path":"must-not-exist.py",'}}]},finish_reason:"tool_calls"}],usage:{prompt_tokens:100,completion_tokens:20}}) + "\n\n");
      } else send("RECOVERED_VALID_JSON: invalid call was not executed.","stop");
      return res.end("data: [DONE]\n\n");
    }
    const wantedTool = prompt.includes("mcp-smoke-stdio") ? "mcp__smoke_stdio__echo" : prompt.includes("mcp-smoke-http") ? "mcp__smoke_http__echo" : prompt.includes("read-real-fixture") ? "read_file" : null;
    if (wantedTool && payload.messages.at(-1)?.role !== "tool") {
      assert(payload.tools.some(tool => tool.function.name === wantedTool), `Tool unavailable: ${wantedTool}`);
      res.write("data: " + JSON.stringify({choices: [{index: 0, delta: {tool_calls: [{index: 0, id: "smoke-call", type: "function", function: {name: wantedTool, arguments: JSON.stringify(wantedTool === "read_file" ? {path: "README.md"} : {message: "local MCP smoke"})}}]}, finish_reason: "tool_calls"}]}) + "\n\n");
      return res.end("data: [DONE]\n\n");
    }
    if (prompt.includes("slow-stream")) {
      const timer = setInterval(() => send("Working… "), 200);
      const end = setTimeout(() => { clearInterval(timer); send("done", "stop"); res.end("data: [DONE]\n\n"); }, 30000);
      res.on("close", () => {clearInterval(timer); clearTimeout(end);});
    } else {
      send("### Completed\n\nRead the project and checked the requested context.\n\n```python\nprint('local agent')\n```\n\n| Check | Result |\n| --- | --- |\n| Local runtime | Ready |\n");
      send("", "stop");
      res.end("data: [DONE]\n\n");
    }
  });
});

async function toggleSettings(page) {
  if (await page.locator(".settings-panel").isVisible()) await page.locator(".settings-header").getByRole("button",{name:"Close",exact:true}).click();
  else await page.getByRole("button",{name:"Settings",exact:true}).click();
}

async function main() {
  await new Promise(resolve => provider.listen(0, "127.0.0.1", resolve));
  const env = {...process.env, ELECTRON_RUN_AS_NODE: undefined, LCA_HEADLESS_SMOKE: process.platform === "win32" ? "0" : "1",
    LCA_DATA_DIR: path.join(data, "agent"), LCA_DESKTOP_DATA_DIR: path.join(data, "desktop"),
    LCA_OLLAMA_URL: `http://127.0.0.1:${provider.address().port}`, LCA_OLLAMA_MODEL: "task-executor",
    LCA_PROVIDER: "openai_compatible", LCA_OPENAI_BASE_URL: `http://127.0.0.1:${provider.address().port}/v1`,
    LCA_OPENAI_MODEL: "smoke-coder", LCA_OPENAI_API_KEY: "", LCA_CONTEXT_RESERVED_OUTPUT_TOKENS: "1024"};
  let application;
  const screenshot = async filename => {
    const page = application.windows()[0];
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.evaluate(() => Promise.race([
      Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))),
      new Promise(resolve => setTimeout(resolve, 1000))
    ]));
    const base64 = await application.evaluate(async ({BrowserWindow}) => {
      const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error("Desktop capture timed out")), 8000));
      return await Promise.race([timeout, (async () => {
      const image = await BrowserWindow.getAllWindows()[0].webContents.capturePage(undefined, {stayHidden: true, stayAwake: true});
      return image.toPNG().toString("base64");
      })()]);
    });
    const bytes = Buffer.from(base64, "base64");
    assert(bytes.length > 1000, "Empty desktop capture");
    fs.writeFileSync(path.join(reportDir, filename), bytes);
  };
  const launch = async () => {
    application = await _electron.launch({executablePath: process.env.LCA_SMOKE_EXECUTABLE || require("../../desktop/node_modules/electron"), args: [...(process.env.LCA_SMOKE_EXECUTABLE ? [] : [path.join(root, "desktop")]), "--disable-gpu", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"], cwd: root, env, timeout: 30000});
    const page = await application.firstWindow();
    page.setDefaultTimeout(20000);
    page.on("pageerror", error => errors.push(String(error)));
    const deadline = Date.now() + 30000;
    let ready = false;
    while (Date.now() < deadline) {
      const status = await page.evaluate(() => window.localAgent.getAgentStatus());
      if (status.state === "ready") { ready = true; break; }
      if (status.state === "error") throw new Error(status.error);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, "Agent did not connect within 30 seconds");
    return page;
  };
  try {
    let page = await launch();
    await application.evaluate(({dialog}, {folder,parent}) => {
      dialog.showOpenDialog = async options => ({canceled:false, filePaths:[options.title === "Choose project location" ? parent : folder]});
    }, {folder:project, parent:data});
    await page.evaluate(() => window.localAgent.openProject("smoke-coder"));
    await page.locator(".composer textarea").waitFor({state: "visible"});
    await page.waitForFunction(() => !document.querySelector(".composer textarea").disabled);
    checks.push("Renderer connects to isolated Python Agent and opens project");
    let draftSession = await page.evaluate(() => window.localAgent.getProject());
    assert.equal(draftSession.payload.threads.length, 0);
    assert.equal(draftSession.payload.active_thread, null);
    for (let i=0;i<3;i++) await page.getByRole("button",{name:"New chat in calculator-project",exact:true}).click();
    await page.locator(".composer textarea").fill("Draft waiting for first send");
    draftSession = await page.evaluate(() => window.localAgent.getProject());
    assert.equal(draftSession.payload.threads.length, 0);
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".execution-summary").waitFor();
    await page.locator(".send-button").waitFor({state:"visible"});
    draftSession = await page.evaluate(() => window.localAgent.getProject());
    assert.equal(draftSession.payload.threads.length, 1);
    assert.equal(draftSession.payload.active_thread.title, "Draft waiting for first send");
    checks.push("Compose icon opens only an in-memory draft; repeated clicks and typing create zero rows, first send creates one named conversation");

    assert.equal(await page.locator(".composer textarea").evaluate(e => getComputedStyle(e).fontSize), "16px");
    assert.equal(await page.locator(".project-tree-name").first().evaluate(e => getComputedStyle(e).fontSize), "14px");
    assert.equal(await page.getByRole("button",{name:"Settings",exact:true}).evaluate(e => getComputedStyle(e).fontSize), "14px");
    checks.push("Readable shared typography: 16px composer, 14px sidebar and controls");
    assert.equal(await page.locator(".sidebar-actions").count(), 0);
    assert.equal(await page.locator(".sidebar-footer .status-dot").count(), 0);
    assert.equal(await page.locator(".provider-pill").count(), 0);
    assert.equal(await page.locator(".topbar").evaluate(e => e.getBoundingClientRect().height), 44);
    assert.equal(await page.locator(".workspace").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(24, 24, 24)");
    assert.equal(await page.locator(".sidebar").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(25, 28, 29)");
    if (process.platform === "win32") assert.equal(await application.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].isMenuBarVisible()), false);
    await page.locator(".projects-heading").getByRole("button",{name:"Add project",exact:true}).click();
    await page.getByRole("menuitem",{name:"Add existing folder",exact:true}).waitFor();
    await screenshot("desktop-project-menu.png");
    await page.keyboard.press("ArrowDown");
    assert.equal(await page.evaluate(() => document.activeElement.textContent), "Create new project");
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("menu").count(), 0);
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute("aria-label")), "Add project");
    await page.locator(".projects-heading").getByRole("button",{name:"Add project",exact:true}).click();
    await page.locator(".composer textarea").click();
    assert.equal(await page.getByRole("menu").count(), 0);
    checks.push("Unified dark palette, single 44px native header, project menu keyboard/outside dismissal, no connection/provider badges");
    assert.equal(await page.locator(".workspace > .topbar").count(), 0);
    assert.equal(await page.locator(".topbar").count(), 1);
    assert.deepEqual(await page.locator(".topbar button").evaluateAll(nodes => nodes.map(e => e.getAttribute("aria-label"))),
      ["Go back","Go forward","Toggle sidebar","文件","编辑","视图","帮助"]);
    assert.equal(await page.locator(".topbar .chat-header-actions, .topbar .chat-header-title").count(), 0);
    assert.equal(await page.locator(".workspace > .chat-header").count(), 1);
    assert(await page.locator(".chat-header").evaluate(e => Math.abs(e.getBoundingClientRect().top - document.querySelector(".topbar").getBoundingClientRect().bottom) <= 1));
    assert.equal(await page.locator(".chat-header-actions").getByRole("button",{name:"Open",exact:true}).count(), 1);
    const beforeNavigation = modelRequests.length;
    await page.getByRole("button",{name:"项目操作：calculator-project",exact:true}).click();
    await page.getByRole("menuitem",{name:"新建会话",exact:true}).click();
    await page.locator(".composer textarea").fill("Unsent navigation draft");
    await page.getByRole("button",{name:"Go back",exact:true}).click();
    await page.locator(".thread-item.active").waitFor();
    await page.getByRole("button",{name:"Go forward",exact:true}).click();
    await page.waitForFunction(() => document.querySelector(".composer textarea").value === "Unsent navigation draft" && !document.querySelector(".thread-item.active"));
    await page.getByRole("button",{name:"Go back",exact:true}).click();
    await page.locator(".thread-item.active").waitFor();
    assert.equal(modelRequests.length,beforeNavigation);
    assert.equal((await page.evaluate(() => window.localAgent.getProject())).payload.threads.length,1);
    await page.getByRole("button",{name:"Toggle sidebar",exact:true}).click();
    assert.equal(await page.locator(".sidebar").isVisible(),false);
    assert(await page.locator(".workspace").evaluate(e => e.getBoundingClientRect().left <= 7));
    assert.equal(await page.locator(".composer textarea").isEnabled(),true);
    await screenshot("desktop-window-toolbar-collapsed.png");
    await page.getByRole("button",{name:"Toggle sidebar",exact:true}).click();
    assert.equal(await page.locator(".sidebar").isVisible(),true);
    checks.push("Window row contains only Back/Forward, sidebar toggle and application menus; chat actions live below, navigation restores draft without model calls or extra threads");
    assert.equal(await page.locator(".topbar").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(26, 34, 37)");
    const appMenus = page.getByRole("menubar",{name:"Application menu"});
    assert.deepEqual(await appMenus.getByRole("menuitem").allTextContents(), ["文件","编辑","视图","帮助"]);
    await appMenus.getByRole("menuitem",{name:"文件",exact:true}).click();
    await page.getByRole("menuitem",{name:"新建项目…",exact:true}).waitFor();
    await page.keyboard.press("Escape");
    await page.locator(".composer textarea").fill("Native edit menu selection");
    await appMenus.getByRole("menuitem",{name:"编辑",exact:true}).click();
    await page.getByRole("menuitem",{name:"全选",exact:true}).click();
    await page.waitForFunction(() => {
      const e = document.querySelector(".composer textarea");
      return document.activeElement === e && e.selectionStart === 0 && e.selectionEnd === e.value.length;
    });
    await page.locator(".composer textarea").fill("");
    await appMenus.getByRole("menuitem",{name:"视图",exact:true}).click();
    await page.getByRole("menuitem",{name:"浅色模式",exact:true}).click();
    await page.waitForFunction(() => document.documentElement.dataset.theme === "light");
    assert.equal(await page.locator(".topbar").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(236, 246, 249)");
    assert.equal(await page.locator(".sidebar").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(248, 252, 253)");
    assert.equal(await page.locator(".composer").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(255, 255, 255)");
    assert.equal(await page.locator(".composer textarea").evaluate(e => getComputedStyle(e).color), "rgb(26, 28, 30)");
    await page.locator(".thread-item").first().hover();
    await page.waitForFunction(() => getComputedStyle(document.querySelector(".thread-item")).backgroundColor === "rgb(235, 240, 241)");
    assert.equal(await page.locator(".welcome-card h1, .message.agent h3").first().evaluate(e => getComputedStyle(e).color), "rgb(26, 28, 30)");
    assert(await page.locator(".composer").evaluate(e => e.getBoundingClientRect().bottom <= innerHeight), "Composer must fit the frame after moving the title bar");
    await screenshot("desktop-reference-light.png");
    await appMenus.getByRole("menuitem",{name:"视图",exact:true}).click();
    await page.getByRole("menuitem",{name:"深色模式",exact:true}).click();
    await page.waitForFunction(() => document.documentElement.dataset.theme === "dark");
    await page.locator(".thread-item").first().hover();
    await page.waitForFunction(() => getComputedStyle(document.querySelector(".thread-item")).backgroundColor === "rgb(44, 46, 46)");
    await screenshot("desktop-reference-dark.png");
    checks.push("Reference-derived cool chrome/near-white sidebar, #181818 dark canvas, one File/Edit/View/Help row, native Select All restores editor focus");
    await toggleSettings(page);
    await page.getByRole("button",{name:"General",exact:true}).click();
    await screenshot("desktop-settings-reference-dark.png");
    assert.equal(await page.locator(".sidebar").isVisible(), false);
    await appMenus.getByRole("menuitem",{name:"视图",exact:true}).click();
    await page.getByRole("menuitem",{name:"浅色模式",exact:true}).click();
    await page.waitForFunction(() => document.documentElement.dataset.theme === "light");
    await screenshot("desktop-settings-reference-light.png");
    assert.equal(await page.locator(".settings-content").evaluate(e => getComputedStyle(e).color), "rgb(26, 28, 30)");
    assert.equal(await page.locator(".settings-nav").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(248, 252, 253)");
    assert.equal(await page.locator(".settings-update-card").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(255, 255, 255)");
    assert.equal(await page.locator(".settings-footer").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(255, 255, 255)");
    assert.equal(await page.locator(".settings-secondary").first().evaluate(e => getComputedStyle(e).backgroundColor), "rgb(255, 255, 255)");
    await toggleSettings(page);
    await appMenus.getByRole("menuitem",{name:"视图",exact:true}).click();
    await page.getByRole("menuitem",{name:"深色模式",exact:true}).click();
    await page.waitForFunction(() => document.documentElement.dataset.theme === "dark");
    checks.push("Dedicated Settings view uses the reference palette without a second project sidebar; editor stays inside viewport");
    const originalOpenPath = await application.evaluate(({shell}) => {
      globalThis.smokeOpenPath = shell.openPath;
      globalThis.smokeOpenWait = new Promise(resolve => {globalThis.smokeOpenResolve = resolve;});
      shell.openPath = async folder => {globalThis.smokeOpenResolve(folder); return "";};
      return true;
    });
    try {
      await page.getByRole("button",{name:"Open",exact:true}).click();
      await page.getByRole("menuitem",{name:process.platform === "win32" ? "Open in File Explorer" : "Open in file manager",exact:true}).click();
      await page.waitForFunction(() => !document.querySelector('[role="menu"]'));
      const opened = await application.evaluate(() => globalThis.smokeOpenWait);
      assert.equal(fs.realpathSync.native(opened), fs.realpathSync.native(project));
    } finally {
      if (originalOpenPath) await application.evaluate(({shell}) => {shell.openPath = globalThis.smokeOpenPath;});
    }
    checks.push("Header Open menu resolves only the active backend project; file manager launch mocked");
    const beforeProtocolRecovery = modelRequests.length;
    await page.locator(".composer textarea").fill("invalid-json-smoke");
    await page.locator(".composer textarea").press("Enter");
    await page.waitForFunction(() => [...document.querySelectorAll(".message.agent")].some(e => e.textContent.includes("RECOVERED_VALID_JSON")) && !document.querySelector(".stop-button"));
    assert(!(await page.locator(".message.agent").allTextContents()).some(text => text.includes("DISCARD_PARTIAL")));
    assert(!fs.existsSync(path.join(project,"must-not-exist.py")));
    assert.equal(modelRequests.length,beforeProtocolRecovery+2);
    checks.push("Actual HTTP malformed tool batch executes no file write, same-model retry is visible, discarded Unicode partial output is removed and final chat recovers");

    if (process.platform === "win32") {
      const captureTitle="LCA M4 controlled Electron capture";
      const beforeCaptureBounds=await application.evaluate(({BrowserWindow,screen},title)=>{const w=BrowserWindow.getAllWindows()[0];const bounds=w.getBounds();const min=w.getMinimumSize();const area=screen.getPrimaryDisplay().workArea;w.setMinimumSize(0,0);w.setTitle(title);w.setBounds({x:area.x+20,y:area.y+20,width:Math.min(1000,area.width-40),height:Math.min(650,area.height-40)});w.setAlwaysOnTop(true);w.show();w.focus();return {bounds,min};},captureTitle);
      const captured=JSON.parse(execFileSync("uv",["run","python","scripts/validation/desktop_window_probe.py","--title",captureTitle,"--authorized","--focus","--report","m4-electron-window.json"],{cwd:root,env:{...process.env,LCA_DATA_DIR:path.join(data,"agent")},encoding:"utf8",timeout:45000}).trim());
      assert(captured.real_windows_api && captured.raw_capture_valid);
      assert(captured.width>0 && captured.height>0);
      assert(["PrintWindow_client","foreground_visible_client"].includes(captured.capture_method));
      const preview=await page.evaluate(p=>window.localAgent.previewScreenshot(p),captured.path);
      assert(preview.startsWith("data:image/png;base64,"));
      await application.evaluate(({BrowserWindow},{bounds,min})=>{const w=BrowserWindow.getAllWindows()[0];w.setAlwaysOnTop(false);w.setBounds(bounds);w.setMinimumSize(...min);},beforeCaptureBounds);
      checks.push("Real Electron HWND/UIA screenshot through product Windows capture with valid dimensions, privacy masking and method diagnostics");
    }
    await page.locator(".projects-heading").getByRole("button", {name:"Add project",exact:true}).click();
    await page.getByRole("menuitem", {name:"Create new project",exact:true}).click();
    let projectDialog = page.getByRole("dialog",{name:"New project",exact:true});
    await projectDialog.waitFor();
    await page.getByLabel("Project name",{exact:true}).fill("do-not-create");
    await page.getByLabel("Project name",{exact:true}).press("Escape");
    await projectDialog.waitFor({state:"hidden"});
    assert(!fs.existsSync(path.join(data,"do-not-create")));
    await page.locator(".projects-heading").getByRole("button", {name:"Add project",exact:true}).click();
    await page.getByRole("menuitem", {name:"Create new project",exact:true}).click();
    projectDialog = page.getByRole("dialog",{name:"New project",exact:true});
    await page.getByLabel("Project name",{exact:true}).fill("calculator-project");
    await projectDialog.getByRole("button",{name:"Choose…",exact:true}).click();
    await page.getByLabel("Project location",{exact:true}).waitFor();
    await page.waitForFunction(parent => document.querySelector('[aria-label="Project location"]').value === parent, data);
    await projectDialog.getByRole("button",{name:"Create project",exact:true}).click();
    await projectDialog.getByRole("alert").waitFor();
    assert((await projectDialog.getByRole("alert").innerText()).includes("already exists"));
    assert(fs.readFileSync(path.join(project,"calculator.py"),"utf8").includes("a - b"));
    await page.getByLabel("Project name",{exact:true}).fill("ui-created-project");
    const projectBounds = await projectDialog.boundingBox();
    const viewport = await page.evaluate(() => ({width:innerWidth,height:innerHeight}));
    assert(Math.abs(projectBounds.x + projectBounds.width/2 - viewport.width/2) < 3);
    assert(Math.abs(projectBounds.y + projectBounds.height/2 - viewport.height/2) < 3);
    await screenshot("desktop-v041-new-project.png");
    await projectDialog.getByRole("button",{name:"Create project",exact:true}).click();
    await projectDialog.waitFor({state:"hidden"});
    await page.locator(".project-tree-name").filter({hasText:"ui-created-project"}).waitFor();
    await page.waitForFunction(() => document.querySelector(".project-tree-name")?.textContent === "ui-created-project");
    checks.push("Newly updated project sorts ahead of alphabetically earlier calculator-project");
    assert(fs.existsSync(path.join(data,"ui-created-project",".git")));
    const newSession = await page.evaluate(() => window.localAgent.getProject());
    assert.equal(fs.realpathSync.native(newSession.payload.project.path), fs.realpathSync.native(path.join(data,"ui-created-project")));
    await page.locator(".projects-heading").getByRole("button", {name:"Add project",exact:true}).click();
    await page.getByRole("menuitem", {name:"Add existing folder",exact:true}).click();
    checks.push("Centered New project dialog: cancellation, location picker, collision protection, Git init and registry open");

    // Reproduce a persisted API model in a thread after switching chat to Ollama.
    // Startup shows the valid local default, but used to send the old API name.
    const previousSettings = await page.evaluate(async () => {
      const settings = {...(await window.localAgent.getSettings()).event.payload};
      delete settings.api_key_configured;
      const session = await window.localAgent.getProject();
      await window.localAgent.selectModel(session.payload.active_thread.id, "DeepSeek-V4-Flash-SaaS");
      await window.localAgent.applySettings({...settings,provider:"ollama",ollama_model:"gpt-oss:20b"});
      return settings;
    });
    await application.close();
    page = await launch();
    // A restored Thread must not silently switch connections. Explicitly select
    // the migrated local profile, then verify the actual HTTP model and persistence.
    await page.getByLabel("Chat model",{exact:true}).selectOption({label:"gpt-oss:20b"});
    const localChatProfile = await page.getByLabel("Chat model",{exact:true}).inputValue();
    assert(localChatProfile.startsWith("profile:"));
    const requestsBeforeChat = modelRequests.length;
    await page.locator(".composer textarea").fill("Check explicitly selected local chat profile");
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".execution-summary").waitFor();
    await page.locator(".send-button").waitFor({state:"visible"});
    assert.deepEqual(modelRequests.slice(requestsBeforeChat), [{url:"/api/chat",model:"gpt-oss:20b"}]);
    assert.equal((await page.evaluate(() => window.localAgent.getProject())).payload.active_thread.active_model,localChatProfile);
    await application.close();
    page = await launch();
    await page.waitForFunction(value => document.querySelector('.model-select')?.value === value,localChatProfile);
    await page.evaluate(settings => window.localAgent.applySettings(settings),previousSettings);
    await application.close();
    page = await launch();
    await page.waitForFunction(value => document.querySelector('.model-select')?.value === value,localChatProfile);
    checks.push("Explicit Profile routes the actual local HTTP model and persists across restart and legacy Provider changes without fallback");
    await page.evaluate(async value => {
      const loaded=(await window.localAgent.taskRequest("","task.catalog.get")).payload;
      loaded.catalog.profiles=loaded.catalog.profiles.filter(p=>"profile:"+p.model_profile_id!==value);
      await window.localAgent.taskRequest("","task.catalog.update",{catalog:loaded.catalog,config:loaded.config});
    },localChatProfile);
    await application.close();page=await launch();
    await page.waitForFunction(value => document.querySelector('.model-select')?.value === value,localChatProfile);
    assert((await page.getByLabel("Chat model",{exact:true}).locator("option:checked").innerText()).includes("unavailable"));
    assert(await page.locator(".send-button").isDisabled());
    await page.getByLabel("Chat model",{exact:true}).selectOption({label:"smoke-coder"});
    await page.waitForFunction(() => !document.querySelector('.composer textarea').disabled);
    checks.push("Removed historical Profile is shown explicitly and blocks Send until a valid saved profile is selected");

    const hostPython = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    const fixture = path.join(root, "tests", "fixtures", "mcp_test_server.py");
    const listener = net.createServer();
    await new Promise(resolve => listener.listen(0, "127.0.0.1", resolve));
    const mcpPort = listener.address().port;
    await new Promise(resolve => listener.close(resolve));
    mcpProcess = spawn(hostPython, [fixture, "--http", "--port", String(mcpPort)], {stdio: "ignore", windowsHide: true});
    const portReady = async () => new Promise(resolve => {
      const socket = net.connect(mcpPort, "127.0.0.1");
      socket.on("connect", () => { socket.destroy(); resolve(true); });
      socket.on("error", () => { socket.destroy(); resolve(false); });
    });
    const mcpDeadline = Date.now() + 15000;
    while (!await portReady()) {
      assert(Date.now() < mcpDeadline && mcpProcess.exitCode === null, "MCP HTTP fixture did not start");
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    await page.evaluate(async ({hostPython, fixture, mcpPort}) => {
      await window.localAgent.upsertMcpServer({name: "smoke_stdio", transport: "stdio", command: hostPython, args: [fixture], enabled: true, trusted: true});
      const configured = await window.localAgent.upsertMcpServer({name: "smoke_http", transport: "streamable_http", url: `http://127.0.0.1:${mcpPort}/mcp`, enabled: true, trusted: true});
      if (configured.event.payload.connected_count !== 2) throw new Error("Both MCP transports must connect");
    }, {hostPython, fixture, mcpPort});
    for (const prompt of ["read-real-fixture", "mcp-smoke-stdio", "mcp-smoke-http"]) {
      const prior = await page.locator(".execution-summary").count();
      await page.locator(".composer textarea").fill(prompt);
      await page.locator(".composer textarea").press("Enter");
      await page.waitForFunction(count => document.querySelectorAll(".execution-summary").length > count, prior);
      await page.locator(".send-button").waitFor();
      assert(await page.locator(".tool-toggle").last().innerText().then(text => text.includes("Completed")), "Tool did not complete");
    }
    checks.push("Real file read and MCP stdio/HTTP calls through the Agent loop");

    // Exercise the actual Settings form, not only the IPC configuration endpoint.
    await toggleSettings(page);
    await page.getByRole("button", {name:"Models & Routing", exact:true}).click();
    await page.getByLabel("Model connection", {exact:true}).waitFor();
    const profileIds = {};
    for (const [kind, name, models] of [["ollama","Company Ollama",["task-planner","task-executor"]],["openai_compatible","Company API",["api-reviewer","api-escalation"]]]) {
      await page.getByRole("button", {name:"Add connection", exact:true}).click();
      await page.getByLabel("Connection name", {exact:true}).fill(name);
      await page.getByLabel("Connection provider type", {exact:true}).selectOption(kind);
      await page.getByLabel("Connection base URL", {exact:true}).fill(`http://127.0.0.1:${provider.address().port}${kind === "ollama" ? "" : "/v1"}`);
      if (kind === "openai_compatible") {
        await page.getByLabel("Connection API key", {exact:true}).fill("mock-only-not-a-real-key");
        await page.getByRole("button", {name:"Save / clear connection key", exact:true}).click();
        await page.getByText(/Credential and connection reference saved:/).waitFor();
      }
      for (const model of models) {
        await page.getByRole("button", {name:"Manually add model", exact:true}).click();
        await page.getByLabel("Profile model ID", {exact:true}).fill(model);
        await page.getByLabel("Profile display name", {exact:true}).fill(model);
        await page.getByLabel("Profile context window", {exact:true}).fill("65536");
        profileIds[model] = await page.getByLabel("Edit model profile", {exact:true}).inputValue();
      }
    }
    const roleChoices = {planner:"task-planner",executor:"task-executor",reviewer:"api-reviewer",escalation:"api-escalation"};
    await page.getByLabel('Profile output limit',{exact:true}).fill('1024');
    await page.getByRole('button',{name:'Use coding output limit',exact:true}).click();
    assert.equal(await page.getByLabel('Profile output limit',{exact:true}).inputValue(),'8192');
    await page.getByLabel('Profile output limit',{exact:true}).fill('16384');
    await page.getByRole('button',{name:'Use coding output limit',exact:true}).click();
    assert.equal(await page.getByLabel('Profile output limit',{exact:true}).inputValue(),'16384');
    await page.getByLabel('Profile output limit',{exact:true}).fill('8192');
    for (const [role,name] of Object.entries(roleChoices)) await page.getByLabel(role + " profile", {exact:true}).selectOption(profileIds[name]);
    await page.getByLabel("Default api_calls",{exact:true}).fill("3");
    await page.getByLabel("Default api_tokens",{exact:true}).fill("30000");
    const beforeLongBudget = modelRequests.length;
    await page.getByRole("button",{name:"Use long task budget",exact:true}).click();
    assert.equal(await page.getByLabel("Default api_calls",{exact:true}).inputValue(),"200");
    assert.equal(await page.getByLabel("Default api_tokens",{exact:true}).inputValue(),"10000000");
    assert.equal(await page.getByLabel("Default global_api_tokens",{exact:true}).inputValue(),"100000000");
    assert.equal(modelRequests.length,beforeLongBudget,"Editing budget must not send model requests");
    await page.getByRole("button", {name:"Save model configuration", exact:true}).click();
    await page.getByText("Model configuration saved. Running task snapshots are unchanged.").waitFor();
    await page.getByRole("button", {name:"Fetch model list (does not verify capabilities)", exact:true}).click();
    await page.getByRole("button", {name:"Add model: smoke-coder", exact:true}).waitFor();
    await screenshot("desktop-mixed-provider-settings.png");
    const persistedRouting = await page.evaluate(async () => (await window.localAgent.taskRequest("", "task.catalog.get")).payload);
    assert.equal(persistedRouting.catalog.profiles.find(p=>p.model_id==='api-escalation').max_output_tokens,8192);
    assert.equal(new Set(Object.values(persistedRouting.config.roles).map(p => p.model_profile_id)).size, 4);
    assert.equal(persistedRouting.config.budget.api_tokens,10000000);
    checks.push("Actual Settings long-task preset saves large budgets without changing role bindings or sending model requests");
    checks.push("Settings creates local/API connections, four model profiles, distinct role bindings and protected key");
    const beforeDiagnosis = modelRequests.length;
    await page.getByRole("button", {name:"Test Vision", exact:true}).click();
    await page.getByText(/配置 PASS · 连接 NOT RUN/).waitFor();
    assert.equal(modelRequests.length,beforeDiagnosis,"Offline diagnosis must not send model requests");
    await page.getByLabel("Enable Live Test", {exact:true}).check();
    await page.getByRole("button", {name:"Test Vision", exact:true}).click();
    await page.getByText(/配置 PASS · 连接 PASS · 文本 PASS · 视觉 FAIL · 工具 PASS/).waitFor();
    assert.equal(modelRequests.length-beforeDiagnosis,3);
    assert((await page.locator('[aria-label="Model connection diagnostics"] pre').innerText()).includes("CAPABILITY_ASSERTION_FAILED"));
    await page.getByLabel("Enable Live Test", {exact:true}).uncheck();
    checks.push("M4 Settings diagnostics: offline zero requests, explicit local Live Test sends real JPEG, HTTP200 wrong-image assertion FAIL, text/native functions PASS, exactly three requests");
    await application.close();
    page = await launch();
    await toggleSettings(page);
    await page.getByRole("button", {name:"Models & Routing", exact:true}).click();
    assert.equal(await page.getByLabel("Default api_tokens",{exact:true}).inputValue(),"10000000");
    for (const [role,name] of Object.entries(roleChoices)) {
      await page.getByLabel(role + " profile", {exact:true}).waitFor();
      assert.equal(await page.getByLabel(role + " profile", {exact:true}).inputValue(), profileIds[name]);
    }
    await page.getByLabel("Model connection", {exact:true}).selectOption({label:"Company API · openai_compatible"});
    protectedCredentialSeen = false;
    await page.getByRole("button", {name:"Fetch model list (does not verify capabilities)", exact:true}).click();
    await page.getByRole("button", {name:"Add model: smoke-coder", exact:true}).waitFor();
    const keyStorage = await page.evaluate(async () => (await window.localAgent.taskRequest("", "task.credential.status")).payload.mode);
    if (keyStorage === "os_protected") {
      assert(protectedCredentialSeen, "Restart lost the protected per-connection key");
      assert(!fs.readFileSync(path.join(data,"desktop","model-secrets.json"),"utf8").includes("mock-only-not-a-real-key"));
    } else skipped.push("OS protected model credentials unavailable; key is session-only as shown in Settings");
    checks.push("Restart restores four distinct role bindings; protected credential reaches the selected API connection");
    await toggleSettings(page);
    const initialChatProfile=await page.getByLabel("Chat model",{exact:true}).inputValue();
    await page.getByLabel("Search chat models",{exact:true}).fill("api-escalation");
    await page.getByLabel("Chat model",{exact:true}).selectOption("profile:"+profileIds["api-escalation"]);
    const priorProfileCalls=modelRequests.length;
    const priorProfileTurns=await page.locator('.execution-summary').count();
    await page.locator('.composer textarea').fill('Confirm independent saved API Chat profile');
    await page.locator('.composer textarea').press('Enter');
    await page.waitForFunction(count=>document.querySelectorAll('.execution-summary').length>count,priorProfileTurns);
    assert.equal(modelRequests[priorProfileCalls].model,'api-escalation');
    await page.getByLabel("Search chat models",{exact:true}).fill("");
    await page.getByLabel("Chat model",{exact:true}).selectOption(initialChatProfile);
    checks.push("Searchable connection-grouped Chat Profile routes selected API independently of Task Executor");

    await page.evaluate(async () => {
      const session = await window.localAgent.getProject();
      const thread = session.payload.active_thread.id;
      const loaded = await window.localAgent.taskRequest(thread, "task.settings.get");
      const config = loaded.payload.config;
      config.budget.api_calls = 0;
      config.verification_commands = ["uv run --no-project python -m unittest discover -s tests -v", "git diff --check"];
      // Use the local Executor also as Reviewer for the zero-API success scenario.
      config.roles.reviewer.model_profile_id = config.roles.executor.model_profile_id;
      await window.localAgent.taskRequest(thread, "task.settings.update", {config});
    });
    await page.getByRole("button", {name:"Task", exact:true}).click();
    await page.getByLabel("Task strategy", {exact:true}).selectOption("local-first");
    await page.getByLabel("Autonomous task goal").fill("Fix calculator in an isolated task worktree");
    await page.getByRole("button", {name:"Start autonomous task", exact:true}).click();
    await page.getByRole("button", {name:"Allow once", exact:true}).click();
    await page.locator('[data-task-status="awaiting_approval"]').waitFor({timeout:60000});
    const timeline=page.locator('summary').filter({hasText:/^Task timeline/}).first();
    await timeline.click();
    await page.getByText('Independent verification #1: PASS',{exact:false}).waitFor();
    assert.equal(await page.locator('.composer textarea').isEnabled(),true);
    checks.push("Task timeline shows persisted independent verification and state transitions while Composer remains usable");
    await page.locator(".send-button").waitFor();
    const taskBefore = await page.evaluate(async () => {
      const session = await window.localAgent.getProject();
      const loaded = await window.localAgent.taskRequest(session.payload.active_thread.id, "task.list");
      return loaded.payload.tasks[0];
    });
    assert.equal(taskBefore.usage.api_calls, 0);
    assert(taskBefore.verification.every(test => test.ok));
    assert(fs.readFileSync(path.join(project,"calculator.py"),"utf8").includes("a - b"));
    assert(fs.readFileSync(path.join(taskBefore.workspace,"calculator.py"),"utf8").includes("a + b"));
    await screenshot("desktop-v04-task-report.png");
    await page.getByRole("button", {name:"Accept verified report", exact:true}).click();
    await page.locator('[data-task-status="completed"]').waitFor();
    checks.push("Autonomous task uses Mock Ollama, actual worktree/tools/tests, zero API and verified report approval");
    blockPlanning = true;
    await page.getByLabel("Autonomous task goal").fill("Cancel a blocked Planning request");
    await page.getByRole("button",{name:"Start autonomous task",exact:true}).click();
    await page.getByRole("button",{name:"Allow once",exact:true}).click();
    await page.waitForFunction(() => !!document.querySelector('.task-live-controls'));
    const cancel = page.getByRole("button",{name:"Cancel active task",exact:true});
    await cancel.waitFor();
    assert(await cancel.isEnabled());
    const planningDeadline = Date.now() + 10000;
    while (!planningRequests && Date.now() < planningDeadline) await new Promise(resolve => setTimeout(resolve,100));
    assert.equal(planningRequests, 1);
    const taskPanel = page.locator(".task-panel");
    await taskPanel.evaluate(el => el.scrollTop = el.scrollHeight);
    const cancelRect = await cancel.boundingBox();
    const taskRect = await taskPanel.boundingBox();
    assert(cancelRect.y >= taskRect.y && cancelRect.y + cancelRect.height <= taskRect.y + taskRect.height);
    await cancel.click();
    await page.locator('[data-task-status="cancelled"]').waitFor();
    blockPlanning = false;
    const cancelledTask = await page.evaluate(async () => {
      const session = await window.localAgent.getProject();
      return (await window.localAgent.taskRequest(session.payload.active_thread.id,"task.list")).payload.tasks[0];
    });
    await page.getByRole("button",{name:"Task diagnostics " + cancelledTask.id.slice(0,8),exact:true}).click();
    const diagnosticPanel = page.getByLabel("Task diagnostics report",{exact:true});
    await diagnosticPanel.waitFor();
    assert((await diagnosticPanel.innerText()).includes("TASK_CANCELLED"));
    assert(await diagnosticPanel.getByRole("button",{name:"Copy diagnostics JSON",exact:true}).isEnabled());
    assert(await diagnosticPanel.getByRole("button",{name:"Copy diagnostics Markdown",exact:true}).isEnabled());
    checks.push("Sticky Task Cancel stops a blocked Planning request; persisted sanitized JSON/Markdown diagnostics are accessible");

    // Exercise ordinary Settings navigation first (App closes the Task panel).
    // Then update saved defaults through RPC while the zero-budget panel stays
    // mounted, covering stale caches from other configuration clients as well.
    const defaultsBeforeBudgetCheck = await page.evaluate(async () => (await window.localAgent.taskRequest("","task.settings.get")).payload.config);
    const saveOnlineDefaults = async calls => {
      await toggleSettings(page);
      await page.getByRole("button",{name:"Models & Routing",exact:true}).click();
      await page.getByLabel("Default execution policy",{exact:true}).selectOption("api-only");
      for (const role of ["planner","executor","reviewer"]) await page.getByLabel(role + " profile",{exact:true}).selectOption(profileIds["api-reviewer"]);
      await page.getByLabel("Default api_calls",{exact:true}).fill(String(calls));
      await page.getByLabel("Default api_tokens",{exact:true}).fill("30000");
      await page.getByRole("button",{name:"Save model configuration",exact:true}).click();
      await page.getByText("Model configuration saved. Running task snapshots are unchanged.").waitFor();
      await toggleSettings(page);
    };
    await saveOnlineDefaults(0);
    await page.getByRole("button",{name:"Task",exact:true}).click();
    const requestsBeforeBlock = modelRequests.length;
    await page.getByLabel("Autonomous task goal").fill("Show exact zero-budget preflight rejection");
    await page.getByRole("button",{name:"Start autonomous task",exact:true}).click();
    await page.getByRole("button",{name:"Allow once",exact:true}).click();
    const budgetDetail = page.getByLabel("Budget rejection details",{exact:true});
    await budgetDetail.waitFor();
    assert((await budgetDetail.innerText()).includes("task / api_calls"));
    assert((await budgetDetail.innerText()).includes("Limit 0 · Used/reserved 0 · This request 1"));
    assert.equal(modelRequests.length,requestsBeforeBlock);
    await page.evaluate(async () => {
      const {config} = (await window.localAgent.taskRequest("","task.settings.get")).payload;
      config.budget.api_calls = 6;
      await window.localAgent.taskRequest("","task.settings.update",{config});
    });
    await page.getByLabel("Autonomous task goal").fill("Use fresh Settings for API Planner and fix calculator");
    await page.getByRole("button",{name:"Start autonomous task",exact:true}).click();
    await page.getByRole("button",{name:"Allow once",exact:true}).click();
    await page.locator('[data-task-status="awaiting_approval"]').waitFor({timeout:60000});
    const latestBudgetTask = await page.evaluate(async () => {
      const session = await window.localAgent.getProject();
      return (await window.localAgent.taskRequest(session.payload.active_thread.id,"task.list")).payload.tasks;
    });
    const freshTask = latestBudgetTask.find(t => t.goal === "Use fresh Settings for API Planner and fix calculator");
    const blockedTask = latestBudgetTask.find(t => t.goal === "Show exact zero-budget preflight rejection");
    assert.equal(freshTask.config.strategy,"api-only");
    assert.equal(freshTask.config.budget.api_calls,6);
    assert.equal(blockedTask.config.budget.api_calls,0);
    assert.equal(freshTask.resolved_roles.planner.model,"api-reviewer");
    assert.equal(freshTask.usage.api_calls,4);
    assert.equal(freshTask.usage.reserved_tokens,480);
    assert(freshTask.verification.every(v => v.ok));
    assert(fs.readFileSync(path.join(freshTask.workspace,"calculator.py"),"utf8").includes("a + b"));
    assert(freshTask.report.diff.includes("+    return a + b"));
    checks.push("Mounted Task panel uses latest Settings for API-only Planner; zero budget gives field-level rejection without HTTP; fresh budget runs real Mock API patch/unittest/Diff and preserves old snapshot");
    await page.evaluate(config => window.localAgent.taskRequest("","task.settings.update",{config}), defaultsBeforeBudgetCheck);
    await page.getByRole("button", {name:"Task", exact:true}).click();
    await page.getByRole("button", {name:"Task", exact:true}).click();
    await page.waitForFunction(() => document.querySelector('[aria-label="Task strategy"]')?.value === "local-first");
    // Select Single Agent using the actual Task UI. Other role bindings remain local.
    await page.getByLabel("Task strategy",{exact:true}).selectOption("single-agent");
    await page.getByText("Models and budget",{exact:true}).click();
    await page.getByLabel("executor task profile",{exact:true}).selectOption(profileIds["api-reviewer"]);
    await page.getByRole("button",{name:"Use long task budget",exact:true}).click();
    assert.equal(await page.getByLabel("api_tokens",{exact:true}).inputValue(),"10000000");
    assert.equal(await page.getByLabel("executor task profile",{exact:true}).inputValue(),profileIds["api-reviewer"]);
    await page.getByLabel("api_calls",{exact:true}).fill("12");
    await page.getByLabel("api_tokens",{exact:true}).fill("250000");
    assert.equal(await page.getByLabel("planner task profile",{exact:true}).count(),0);
    const m1Start = modelRequests.length;
    await page.getByLabel("Autonomous task goal").fill("M1 Single Agent: inspect calculator, run failing tests, fix, retest and inspect diff");
    await page.getByRole("button",{name:"Start autonomous task",exact:true}).click();
    await page.getByRole("button",{name:"Allow once",exact:true}).click();
    let m1Task;
    const m1Deadline = Date.now() + 60000;
    while (Date.now() < m1Deadline) {
      m1Task = await page.evaluate(async () => {
        const session = await window.localAgent.getProject();
        return (await window.localAgent.taskRequest(session.payload.active_thread.id,"task.list")).payload.tasks.find(t => t.goal.startsWith("M1 Single Agent"));
      });
      if (m1Task && ["awaiting_approval","paused","failed"].includes(m1Task.status)) break;
      await new Promise(resolve => setTimeout(resolve,200));
    }
    assert.equal(m1Task.status,"awaiting_approval",m1Task.reason);
    assert.equal(m1Task.config.strategy,"single-agent");
    assert.equal(m1Task.planning_attempts ?? 0,0);
    assert.equal(m1Task.escalations,0);
    assert.equal(modelRequests.length-m1Start,6);
    assert(modelRequests.slice(m1Start).every(r => r.model === "api-reviewer" && r.url.endsWith("/chat/completions")));
    assert(m1Task.calls.every(c => c.role === "executor"));
    assert(m1Task.verification.every(r => r.ok));
    assert(fs.readFileSync(path.join(m1Task.workspace,"calculator.py"),"utf8").includes("a + b  # M1 fix"));
    assert(fs.readFileSync(path.join(project,"calculator.py"),"utf8").includes("a - b"));
    assert(m1Task.report.diff.includes("M1 fix"));
    await screenshot("desktop-m1-single-agent.png");
    checks.push("M1 Single Agent UI: one online Executor, six model rounds, real failing tests/patch/retest/Diff, no Planner/Reviewer/escalation requests");
    await page.getByRole("button", {name:"Task", exact:true}).click();

    const retainedMemory = m1Task.plan.execution.working_memory;
    assert(retainedMemory.sequence >= 5);
    assert(retainedMemory.changed_paths.includes("calculator.py"));
    assert.equal(retainedMemory.last_command.exit_code,0);
    const beforeInspectingMemory = modelRequests.length;
    await page.getByRole("button", {name:"More",exact:true}).click();
    await page.getByRole("menuitem", {name:"Plan",exact:true}).click();
    const memorySection = page.locator('.context-section').filter({has:page.getByRole("heading",{name:m1Task.goal,exact:true})});
    const memoryDetail = memorySection.locator('details.agent-context-evidence');
    await memoryDetail.waitFor();
    assert.equal(await memoryDetail.getAttribute('open'),null);
    await memoryDetail.locator('summary').click();
    assert((await memoryDetail.innerText()).includes("不代表当前文件已通过验证"));
    assert((await memoryDetail.innerText()).includes("calculator.py"));
    assert((await memoryDetail.innerText()).includes("Exit 0（历史）"));
    await page.locator('.composer textarea').fill('Unsent draft while inspecting execution context');
    assert.equal(await page.locator('.composer textarea').isEnabled(),true);
    await page.locator('.composer textarea').fill('');
    assert.equal(modelRequests.length,beforeInspectingMemory);
    await page.getByRole("button", {name:"More",exact:true}).click();
    await page.getByRole("menuitem", {name:"Plan",exact:true}).click();
    checks.push("Actual Plan UI exposes collapsed durable tool facts and historical test results without covering composer or requesting models");

    for (const panel of ["Task", "Context", "Git", "Plan", "Diagnostics"]) {
      if (["Plan", "Diagnostics"].includes(panel)) {
        await page.getByRole("button", {name:"More",exact:true}).click();
        await page.getByRole("menuitem", {name:panel,exact:true}).click();
      } else await page.getByRole("button", {name: panel, exact: true}).click();
      const composer = await page.locator(".composer").boundingBox();
      const drawer = await page.locator(".conversation-shell > aside, .conversation-shell > .diagnostics-panel").boundingBox();
      assert(drawer.y + drawer.height <= composer.y + 2, `${panel} overlaps composer`);
      const previous = await page.locator(".execution-summary").count();
      await page.locator(".composer textarea").fill(`Inspect project with ${panel} open`);
      await page.locator(".composer textarea").press("Enter");
      await page.waitForFunction(count => document.querySelectorAll(".execution-summary").length > count, previous);
      await page.locator(".send-button").waitFor({state: "visible"});
      checks.push(`Send works with ${panel} open and composer remains unobstructed`);
    }
    await page.getByRole("button", {name:"More",exact:true}).click();
    await page.getByRole("menuitem", {name:"Diagnostics",exact:true}).click();
    assert(await page.locator(".message.agent h3").count() > 0);
    assert(await page.locator(".message.agent table").count() > 0);
    const codeBlock = page.locator(".message.agent .code-block").filter({hasText:"print('local agent')"}).first();
    await codeBlock.getByRole("button", {name:"Copy code", exact:true}).click();
    await codeBlock.getByRole("button", {name:"Copied", exact:true}).waitFor();
    let copied = "";
    for (let retry = 0; retry < 10; retry++) {
      copied = await application.evaluate(({clipboard}) => clipboard.readText());
      if (copied.includes("print('local agent')")) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (!copied.includes("print('local agent')")) {
      const probe = await application.evaluate(({clipboard}) => {clipboard.writeText("lca-native-clipboard-probe"); return clipboard.readText();});
      if (probe === "lca-native-clipboard-probe") throw new Error(`Code copy failed while native clipboard is available: ${JSON.stringify(copied)}`);
      skipped.push("Native clipboard readback unavailable in this Windows session; renderer copy acknowledgement observed, OS clipboard content requires real-session verification");
      checks.push("Markdown headings, fenced code, tables and copy button acknowledgement");
    } else checks.push("Markdown headings, fenced code, tables and actual code clipboard");

    const blockedPlan = await page.evaluate(async () => {
      const session = await window.localAgent.getProject();
      const thread = session.payload.active_thread.id;
      const created = await window.localAgent.planRequest(thread, "plan.create", {goal: "Blocked submission fixture", steps: [{description: "Resolve blocker"}]});
      const plan = created.payload.plans[0];
      await window.localAgent.planRequest(thread, "plan.step.update", {plan_id: plan.id, step_id: plan.steps[0].id, state: "blocked"});
      return {thread, plan: plan.id, step: plan.steps[0].id};
    });
    await page.locator(".composer textarea").fill("Keep this draft when start fails");
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".composer .error-banner").waitFor();
    assert.equal(await page.locator(".composer textarea").inputValue(), "Keep this draft when start fails");
    const recoveredPlan = await page.evaluate(ids => window.localAgent.planRequest(ids.thread, "plan.recover", {plan_id:ids.plan}), blockedPlan);
    const recoveredStep = recoveredPlan.payload.plans.find(p => p.id === blockedPlan.plan).steps[0];
    assert.equal(recoveredStep.state,"in_progress");
    assert.equal(recoveredStep.executions.at(-1).tool,"list_directory");
    assert.equal(recoveredStep.executions.at(-1).status,"succeeded");
    // Recovery discovers real state; it must not manufacture completed evidence.
    assert.notEqual(recoveredStep.state,"completed");
    await page.evaluate(ids => window.localAgent.planRequest(ids.thread, "plan.step.update", {plan_id: ids.plan, step_id: ids.step, state: "skipped"}), blockedPlan);
    checks.push("Failed send preserves draft");
    checks.push("Blocked plan safely recovers through a real workspace probe without forged completion or replay");

    await page.locator(".composer textarea").fill("slow-stream");
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".stop-button").click();
    await page.locator(".send-button").waitFor({state: "visible"});
    checks.push("Stop cancels an active provider stream");

    await page.getByRole("button", {name: "New chat in calculator-project", exact: true}).click();
    await page.locator(".composer textarea").fill("A fresh thread can send messages");
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".message.agent h3").waitFor();
    await page.locator(".send-button").waitFor({state: "visible"});
    await page.locator(".thread-item.active").click({button: "right"});
    await page.getByRole("menuitem",{name:"Rename",exact:true}).click();
    const renameDialog = page.getByRole("dialog",{name:"Rename thread",exact:true});
    await renameDialog.waitFor();
    const renameBounds = await renameDialog.boundingBox();
    const renameViewport = await page.evaluate(() => ({width:innerWidth,height:innerHeight}));
    assert(Math.abs(renameBounds.x + renameBounds.width/2 - renameViewport.width/2) < 3);
    assert(Math.abs(renameBounds.y + renameBounds.height/2 - renameViewport.height/2) < 3);
    assert.equal(await renameDialog.evaluate(e => e.closest(".sidebar")), null);
    await screenshot("desktop-v041-rename.png");
    await page.locator("#thread-rename-input").fill("验收会话");
    await page.locator("#thread-rename-input").press("Enter");
    await page.getByRole("button", {name: "验收会话", exact: true}).waitFor();
    await page.locator(".thread-row").filter({has:page.locator(".thread-item.active")}).getByRole("button",{name:"More actions for 验收会话",exact:true}).click();
    await page.getByRole("menuitem",{name:"Rename",exact:true}).click();
    await page.locator("#thread-rename-input").fill("Cancel this rename");
    await page.locator("#thread-rename-input").press("Escape");
    await page.getByRole("dialog",{name:"Rename thread",exact:true}).waitFor({state:"hidden"});
    await page.getByRole("button", {name: "验收会话", exact: true}).waitFor();
    checks.push("New thread sends; context/ellipsis menu opens centered rename, Enter saves and Escape cancels");

    await screenshot("desktop-dark.png");
    await page.getByRole("button", {name:"More",exact:true}).click();
    await page.getByRole("menuitem", {name:"Toggle color theme",exact:true}).click();
    await screenshot("desktop-light.png");
    assert.equal(await page.locator(".workspace").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(255, 255, 255)");
    assert.equal(await page.locator(".sidebar").evaluate(e => getComputedStyle(e).backgroundColor), "rgb(248, 252, 253)");
    checks.push("Light palette and native header follow the same theme");
    for (const width of [1180, 900]) {
      await application.evaluate(({BrowserWindow}, width) => BrowserWindow.getAllWindows()[0].setSize(width, 780), width);
      await page.getByRole("button", {name: "Context", exact: true}).click();
      await page.locator(".context-overlay").waitFor({state: "visible"});
      assert.equal(await page.locator(".topbar").evaluate(e => e.getBoundingClientRect().height), 44);
      assert.equal(await page.locator(".chat-header-actions").evaluate(e => getComputedStyle(e).flexWrap), "nowrap");
      const actionRects = await page.locator(".chat-header-actions > button").evaluateAll(nodes => nodes.map(e => ({top:e.getBoundingClientRect().top, right:e.getBoundingClientRect().right})));
      assert(actionRects.every(rect => Math.abs(rect.top - actionRects[0].top) < 1), "Every header action must share one row");
      assert(actionRects.every(rect => rect.top >= 44 && rect.right < width), "Chat actions belong below the native window buttons");
      await screenshot(`desktop-context-${width}.png`);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Horizontal page overflow");
      assert(await page.locator(".chat-header-actions").evaluate(e => e.scrollWidth <= e.clientWidth + 1), "Chat controls must fit without scrolling");
      await page.getByRole("button", {name: "Context", exact: true}).click();
      await page.locator(".context-overlay").waitFor({state: "hidden"});
      await toggleSettings(page);
      await page.getByRole("button",{name:"Models & Routing",exact:true}).click();
      await page.getByLabel("Connection name",{exact:true}).waitFor();
      assert.equal(await page.getByLabel("Connection name",{exact:true}).evaluate(e => getComputedStyle(e).fontSize),"14px");
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Settings page overflow");
      await screenshot(`desktop-v041-settings-${width}.png`);
      await toggleSettings(page);
    }
    checks.push("Light/dark themes, 1180/900px window sizes and panel layout");
    await application.close();
    page = await launch();
    await page.getByRole("button", {name: "验收会话", exact: true}).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light");
    assert(await page.locator(".message.agent h3").count() > 0);
    checks.push("Restart restores thread, message history, expansion and theme");
    const restoredMemory = await page.evaluate(async ({id,thread}) => {
      const tasks = (await window.localAgent.taskRequest(thread,"task.list")).payload.tasks;
      return tasks.find(task=>task.id===id)?.plan?.execution?.working_memory;
    },{id:m1Task.id,thread:m1Task.thread_id});
    assert.deepEqual(restoredMemory,retainedMemory);
    checks.push("Actual Electron/Agent restart retains identical task working memory and historical verification facts");
    assert(await page.locator(".project-tree-name").filter({hasText:"ui-created-project"}).count() === 1);
    checks.push("Restart restores the project created through the dialog");
    await toggleSettings(page);
    await page.getByRole("button", {name:"Models & Routing", exact:true}).click();
    await page.getByLabel("executor profile", {exact:true}).waitFor();
    assert.equal(await page.getByLabel("executor profile", {exact:true}).inputValue(), profileIds["task-executor"]);
    assert.equal(await page.getByLabel("escalation profile", {exact:true}).inputValue(), profileIds["api-escalation"]);
    const afterRestart = await page.evaluate(async () => (await window.localAgent.taskRequest("", "task.catalog.get")).payload.catalog);
    assert.deepEqual(afterRestart, persistedRouting.catalog);
    checks.push("Restart restores multiple connections, model identities and role routing");
    await toggleSettings(page);
    await page.locator(".project-tree-header.active").click();
    await application.close();
    page = await launch();
    assert.equal(await page.locator(".project-tree-header.active").getAttribute("aria-expanded"), "false");
    checks.push("Collapsed project remains collapsed after restart");
    // Compose in an inactive empty project: no database row until content is sent.
    const currentSession = await page.evaluate(() => window.localAgent.getProject());
    const currentCount = currentSession.payload.threads.length;
    await page.getByRole("button",{name:"New chat in ui-created-project",exact:true}).click();
    await page.waitForFunction(() => document.querySelector(".project-tree-header.active .project-tree-name")?.textContent === "ui-created-project");
    let otherSession = await page.evaluate(() => window.localAgent.getProject());
    assert.equal(otherSession.payload.threads.length, 0);
    await page.locator(".composer textarea").fill("Persist only this submitted conversation");
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".execution-summary").waitFor();
    await page.locator(".send-button").waitFor({state:"visible"});
    otherSession = await page.evaluate(() => window.localAgent.getProject());
    assert.equal(otherSession.payload.threads.length, 1);
    const newId = otherSession.payload.active_thread.id;

    // Reproduce the common failed-delete case: a persisted paused task, with
    // zero API budget. This is an actual TaskService path, not a fabricated row.
    const deletionProject = path.join(data,"ui-created-project");
    fs.writeFileSync(path.join(deletionProject,"README.md"),"# Conversation deletion fixture\n");
    for (const args of [["config","user.name","Smoke"],["config","user.email","smoke@example.test"],["add","."],["commit","-qm","owned deletion fixture"]]) execFileSync("git",args,{cwd:deletionProject});
    const beforeDeleteRequests = modelRequests.length;
    const pauseReply = await page.evaluate(async ({thread,profile}) => {
      const config = structuredClone((await window.localAgent.taskRequest(thread,"task.settings.get")).payload.config);
      config.strategy = "single-agent";
      config.roles.executor = {model_profile_id:profile};
      config.budget.api_calls = 0;
      config.verification_commands = ["git diff --check"];
      return window.localAgent.taskRequest(thread,"task.start",{goal:"Persist a paused task for conversation deletion regression",config});
    },{thread:newId,profile:profileIds["api-reviewer"]});
    const pausedDeleteTaskId = pauseReply.payload.task.id;
    await page.getByRole("button",{name:"Allow once",exact:true}).click();
    let pausedDeleteTask;
    for (let attempt=0;attempt<100;attempt++) {
      pausedDeleteTask = (await page.evaluate(thread => window.localAgent.taskRequest(thread,"task.list"),newId)).payload.tasks.find(t=>t.id===pausedDeleteTaskId);
      if (pausedDeleteTask?.status==="paused") break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    assert.equal(pausedDeleteTask.status,"paused");
    assert.equal(pausedDeleteTask.usage.api_calls,0);
    assert.equal(modelRequests.length,beforeDeleteRequests);
    assert.equal((await page.evaluate(() => window.localAgent.listProjects())).payload.projects.find(p => p.name === "calculator-project").thread_count, currentCount);
    await application.close();
    page = await launch();
    await page.waitForFunction(() => document.querySelector(".project-tree-name")?.textContent === "ui-created-project");
    assert.equal(await page.locator(".thread-item.active").count(), 1);
    await page.locator(".thread-item.active").click({button:"right"});
    await page.getByRole("menuitem",{name:"Delete",exact:true}).click();
    const deleteDialog = page.getByRole("dialog",{name:"Delete conversation?",exact:true});
    await deleteDialog.getByRole("button",{name:"Cancel",exact:true}).click();
    assert.equal((await page.evaluate(() => window.localAgent.getProject())).payload.active_thread.id, newId);
    await page.locator(".thread-item.active").click({button:"right"});
    await page.getByRole("menuitem",{name:"Delete",exact:true}).click();
    await deleteDialog.getByRole("button",{name:"Delete conversation",exact:true}).click();
    await deleteDialog.waitFor({state:"hidden"});
    assert.equal((await page.evaluate(() => window.localAgent.getProject())).payload.threads.length, 0);
    const cancelledDeleteStatus = execFileSync("uv",["run","--no-project","python","-c",
      "import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); r=c.execute('SELECT data_json FROM autonomous_tasks WHERE plan_id=?',(sys.argv[2],)).fetchone(); print(json.loads(r[0])['status']); c.close()",
      path.join(data,"agent","local-coding-agent.sqlite3"),pausedDeleteTaskId],{cwd:root,encoding:"utf8"}).trim();
    assert.equal(cancelledDeleteStatus,"cancelled");
    assert.equal(modelRequests.length,beforeDeleteRequests);
    checks.push("Confirmed deletion cancels an actual persisted paused task with zero additional model requests and retained task audit");
    assert(fs.existsSync(path.join(data,"ui-created-project",".git")));
    await application.close();
    page = await launch();
    const emptyRestored = await page.evaluate(() => window.localAgent.getProject());
    assert.equal(emptyRestored.payload.threads.length,0);
    assert.equal(emptyRestored.payload.active_thread,null);
    await page.waitForFunction(() => !document.querySelector(".composer textarea").disabled);
    assert.equal(await page.locator(".sidebar-footer .status-title").count(), 0);
    await page.getByRole("button",{name:"Toggle sidebar",exact:true}).click();
    await application.close();
    page = await launch();
    assert.equal(await page.locator(".sidebar").isVisible(),false);
    assert.equal(await page.getByRole("button",{name:"Toggle sidebar",exact:true}).getAttribute("aria-expanded"),"false");
    await page.getByRole("button",{name:"Toggle sidebar",exact:true}).click();
    assert.equal(await page.locator(".sidebar").isVisible(),true);
    checks.push("Sidebar collapse survives restart and can be restored from the window row with an empty project and usable composer");
    checks.push("Compose selects the correct project, submitted chat survives restart, right-click Delete supports cancel and persistence without removing project files");

    // Real project menu/registration persistence; no model response is involved.
    const beforeProjectRequests = modelRequests.length;
    const projectListBefore = (await page.evaluate(() => window.localAgent.listProjects())).payload.projects;
    const calculatorBefore = projectListBefore.find(p => p.name === "calculator-project");
    const activeBefore = (await page.evaluate(() => window.localAgent.getProject())).payload.project.id;
    const projectRow = page.locator(".project-row").filter({has:page.getByText("calculator-project",{exact:true})});
    const moreRect = await projectRow.locator(".project-actions").boundingBox();
    const composeRect = await projectRow.locator(".project-new-chat").boundingBox();
    assert(moreRect.x + moreRect.width <= composeRect.x);
    const openCalculatorMenu = async () => page.getByRole("button",{name:"项目操作：calculator-project",exact:true}).click();
    await openCalculatorMenu();
    const menuLabels = await page.getByRole("menu",{name:"项目操作：calculator-project",exact:true}).getByRole("menuitem").allTextContents();
    assert.deepEqual(menuLabels.slice(0,3), ["新建会话",process.platform==="win32" ? "在文件资源管理器中打开" : "在文件管理器中打开","复制项目路径"]);
    assert.equal(menuLabels.at(-1),"移出项目");
    assert.equal(await page.getByRole("separator").count(),1);
    await screenshot("desktop-project-actions.png");
    await page.keyboard.press("End");
    assert.equal(await page.evaluate(() => document.activeElement.textContent),"移出项目");
    await page.keyboard.press("Escape");
    await openCalculatorMenu();
    await page.getByRole("menuitem",{name:"复制项目路径",exact:true}).click();
    assert.equal(fs.realpathSync.native(await application.evaluate(({clipboard})=>clipboard.readText())),fs.realpathSync.native(project));
    await application.evaluate(({shell})=>{
      globalThis.projectMenuOriginalOpen = shell.openPath;
      globalThis.projectMenuOpenWait = new Promise(resolve=>{globalThis.projectMenuOpenResolve=resolve;});
      shell.openPath=async folder=>{globalThis.projectMenuOpenResolve(folder);return "";};
    });
    try {
      await openCalculatorMenu();
      await page.getByRole("menuitem",{name:process.platform==="win32" ? "在文件资源管理器中打开" : "在文件管理器中打开",exact:true}).click();
      assert.equal(fs.realpathSync.native(await application.evaluate(()=>globalThis.projectMenuOpenWait)),fs.realpathSync.native(project));
      assert.equal((await page.evaluate(()=>window.localAgent.getProject())).payload.project.id,activeBefore);
    } finally {await application.evaluate(({shell})=>{shell.openPath=globalThis.projectMenuOriginalOpen;});}
    const wasExpanded = await projectRow.locator(".project-tree-header").getAttribute("aria-expanded") === "true";
    await openCalculatorMenu();
    await page.getByRole("menuitem",{name:wasExpanded ? "折叠会话" : "展开会话",exact:true}).click();
    assert.equal(await projectRow.locator(".project-tree-header").getAttribute("aria-expanded"),String(!wasExpanded));
    assert.equal((await page.evaluate(()=>window.localAgent.getProject())).payload.project.id,activeBefore);
    checks.push("Project ellipsis is immediately before compose; keyboard menu, scoped folder open, native path copy and expansion preserve the active project");

    const counts = () => JSON.parse(execFileSync("uv",["run","--no-project","python","-c",
      "import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); p=sys.argv[2]; t=[r[0] for r in c.execute('SELECT id FROM threads WHERE project_id=?',(p,))]; a=[r[0] for r in c.execute('SELECT id FROM task_plans WHERE thread_id IN (SELECT id FROM threads WHERE project_id=?)',(p,))]; n=c.execute('SELECT count(*) FROM model_requests WHERE plan_id IN (SELECT id FROM task_plans WHERE thread_id IN (SELECT id FROM threads WHERE project_id=?))',(p,)).fetchone()[0]; print(json.dumps([len(t),len(a),n])); c.close()",
      path.join(data,"agent","local-coding-agent.sqlite3"),calculatorBefore.id],{cwd:root,encoding:"utf8"}));
    const auditBefore = counts();
    assert(auditBefore[0]>0 && auditBefore[1]>0 && auditBefore[2]>0);
    const originalCode = fs.readFileSync(path.join(project,"calculator.py"));
    const worktreesBefore = execFileSync("git",["worktree","list","--porcelain"],{cwd:project,encoding:"utf8"});
    const confirmRemoval = async name => {
      await page.getByRole("button",{name:"项目操作："+name,exact:true}).click();
      await page.getByRole("menuitem",{name:"移出项目",exact:true}).click();
      return page.getByRole("dialog",{name:"移出项目？",exact:true});
    };
    let removeDialog = await confirmRemoval("calculator-project");
    await removeDialog.getByRole("button",{name:"取消",exact:true}).click();
    assert.equal((await page.evaluate(()=>window.localAgent.listProjects())).payload.projects.length,2);
    removeDialog = await confirmRemoval("calculator-project");
    await removeDialog.getByRole("button",{name:"移出项目",exact:true}).click();
    await removeDialog.waitFor({state:"hidden"});
    assert.equal((await page.evaluate(()=>window.localAgent.getProject())).payload.project.id,activeBefore);
    assert.deepEqual(counts(),auditBefore);
    assert.deepEqual(fs.readFileSync(path.join(project,"calculator.py")),originalCode);
    assert.equal(execFileSync("git",["worktree","list","--porcelain"],{cwd:project,encoding:"utf8"}),worktreesBefore);
    await application.close(); page=await launch();
    assert.equal(await page.getByRole("button",{name:"项目操作：calculator-project",exact:true}).count(),0);
    await application.evaluate(({dialog},folder)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});},project);
    await page.locator(".projects-heading").getByRole("button",{name:"Add project",exact:true}).click();
    await page.getByRole("menuitem",{name:"Add existing folder",exact:true}).click();
    await page.waitForFunction(()=>document.querySelector(".project-tree-header.active")?.textContent.includes("calculator-project"));
    const reopened = (await page.evaluate(()=>window.localAgent.getProject())).payload;
    assert.equal(reopened.project.id,calculatorBefore.id);
    assert.deepEqual(reopened.threads.map(t=>t.id).sort(),calculatorBefore.threads.map(t=>t.id).sort());
    assert(reopened.messages.length>0);
    assert.deepEqual(counts(),auditBefore);
    checks.push("Inactive project removal supports cancel, persists across restart and restores original conversations, task audit and Git worktrees on adding the same folder");

    removeDialog = await confirmRemoval("calculator-project");
    await removeDialog.getByRole("button",{name:"移出项目",exact:true}).click();
    await removeDialog.waitFor({state:"hidden"});
    assert.equal((await page.evaluate(()=>window.localAgent.getProject())).payload.project.id,activeBefore);
    removeDialog = await confirmRemoval("ui-created-project");
    await removeDialog.getByRole("button",{name:"移出项目",exact:true}).click();
    await removeDialog.waitFor({state:"hidden"});
    assert.equal((await page.evaluate(()=>window.localAgent.getProject())).payload.project,null);
    assert.equal(await page.getByRole("button",{name:"Go back",exact:true}).isEnabled(),false);
    await application.close(); page=await launch();
    assert.equal((await page.evaluate(()=>window.localAgent.listProjects())).payload.projects.length,0);
    assert.equal((await page.evaluate(()=>window.localAgent.getProject())).payload.project,null);
    assert(fs.existsSync(path.join(project,"calculator.py")) && fs.existsSync(path.join(deletionProject,"README.md")));
    assert.equal(modelRequests.length,beforeProjectRequests);
    checks.push("Removing active and last projects selects a safe fallback or empty landing, prunes navigation and survives restart without deleting files or generating model requests");
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, checks, skipped}, null, 2));
    fs.writeFileSync(path.join(reportDir, "desktop-smoke.json"), JSON.stringify({ok: true, checks, skipped}, null, 2));
  } catch (error) {
    if (application) {
      const page = application.windows()[0];
      if (page) {
        await screenshot("desktop-failure.png").catch(() => {});
        console.error(await page.evaluate(() => ({draft: document.querySelector(".composer textarea")?.value,
          stop: !!document.querySelector(".stop-button"), errors: [...document.querySelectorAll(".error-banner")].map(e => e.textContent),
          messages: document.querySelectorAll(".message.agent").length, metrics: document.querySelectorAll(".execution-summary").length})));
      }
    }
    if (fs.existsSync(path.join(data, "desktop", "logs"))) fs.cpSync(path.join(data, "desktop", "logs"), path.join(reportDir, "desktop-smoke-logs"), {recursive: true});
    fs.writeFileSync(path.join(reportDir, "desktop-smoke.json"), JSON.stringify({ok: false, checks, error: String(error), errors}, null, 2));
    throw error;
  } finally {
    if (application) await application.close().catch(() => {});
    if (mcpProcess && mcpProcess.exitCode === null) {
      const exited = new Promise(resolve => mcpProcess.once("exit", resolve));
      mcpProcess.kill();
      await exited;
    }
    provider.closeAllConnections();
    await new Promise(resolve => provider.close(resolve));
    const resolved = path.resolve(data);
    assert(resolved.startsWith(path.resolve(os.tmpdir()) + path.sep) && path.basename(resolved).startsWith("lca-ui-"));
    fs.rmSync(resolved, {recursive: true, force: true});
  }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
