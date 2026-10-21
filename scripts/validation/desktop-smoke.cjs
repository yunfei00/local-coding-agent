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
let mcpProcess;
const checks = [];
const skipped = [];
const errors = [];
const provider = http.createServer((req, res) => {
  if (req.url === "/api/tags") {res.writeHead(200, {"Content-Type":"application/json"}); return res.end(JSON.stringify({models:[{name:"task-executor"}]}));}
  if (req.url.endsWith("/models")) {
    res.writeHead(rejectModels ? 503 : 200, {"Content-Type": "application/json"});
    return res.end(JSON.stringify(rejectModels ? {error: {message: "Intentional startup failure"}} : {data: [{id: "smoke-coder"}]}));
  }
  let body = "";
  req.on("data", chunk => body += chunk);
  req.on("end", () => {
    const payload = JSON.parse(body || "{}");
    if (req.url === "/api/show") {res.writeHead(200, {"Content-Type":"application/json"}); return res.end(JSON.stringify({capabilities:["tools"]}));}
    if (req.url === "/api/chat") {
      let message = {content:"Task implementation complete"};
      if (payload.model === "task-planner") message.content = JSON.stringify({steps:[{description:"Fix calculator using actual tools"}]});
      else if (payload.model === "task-reviewer") message.content = "Tests passed; review isolated Diff before Git actions.";
      else if (!payload.messages.some(m => m.role === "tool" && (m.name === "apply_patch" || m.tool_name === "apply_patch"))) message = {content:"", tool_calls:[{function:{name:"apply_patch", arguments:{path:"calculator.py", old_text:"return a - b", new_text:"return a + b"}}}]};
      res.writeHead(200, {"Content-Type":"application/x-ndjson"});
      return res.end(JSON.stringify({message, done:true, prompt_eval_count:120, eval_count:30}) + "\n");
    }
    const prompt = payload.messages?.filter(m => m.role === "user").at(-1)?.content ?? "";
    res.writeHead(200, {"Content-Type": "text/event-stream"});
    const send = (text, finish = null) => res.write("data: " + JSON.stringify({choices: [{index: 0, delta: {content: text}, finish_reason: finish}]}) + "\n\n");
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

async function main() {
  await new Promise(resolve => provider.listen(0, "127.0.0.1", resolve));
  const env = {...process.env, ELECTRON_RUN_AS_NODE: undefined, LCA_HEADLESS_SMOKE: "1",
    LCA_DATA_DIR: path.join(data, "agent"), LCA_DESKTOP_DATA_DIR: path.join(data, "desktop"),
    LCA_OLLAMA_URL: `http://127.0.0.1:${provider.address().port}`, LCA_OLLAMA_MODEL: "task-executor",
    LCA_PROVIDER: "openai_compatible", LCA_OPENAI_BASE_URL: `http://127.0.0.1:${provider.address().port}/v1`,
    LCA_OPENAI_MODEL: "smoke-coder", LCA_OPENAI_API_KEY: "", LCA_CONTEXT_RESERVED_OUTPUT_TOKENS: "1024"};
  let application;
  const screenshot = async filename => {
    const page = application.windows()[0];
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
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
    await application.evaluate(({dialog}, folder) => { dialog.showOpenDialog = async () => ({canceled: false, filePaths: [folder]}); }, project);
    await page.evaluate(() => window.localAgent.openProject("smoke-coder"));
    await page.locator(".composer textarea").waitFor({state: "visible"});
    await page.waitForFunction(() => !document.querySelector(".composer textarea").disabled);
    checks.push("Renderer connects to isolated Python Agent and opens project");

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

    await page.evaluate(async () => {
      const session = await window.localAgent.getProject();
      const thread = session.payload.active_thread.id;
      const loaded = await window.localAgent.taskRequest(thread, "task.settings.get");
      const config = loaded.payload.config;
      config.budget.api_calls = 0;
      config.verification_commands = ["uv run --no-project python -m unittest discover -s tests -v", "git diff --check"];
      for (const [role, profile] of Object.entries(config.roles)) {profile.model = "task-" + role; profile.context_window = 65536;}
      await window.localAgent.taskRequest(thread, "task.settings.update", {config});
    });
    await page.getByRole("button", {name:"Task", exact:true}).click();
    await page.getByLabel("Task strategy", {exact:true}).selectOption("local-first");
    await page.getByLabel("Autonomous task goal").fill("Fix calculator in an isolated task worktree");
    await page.getByRole("button", {name:"Start autonomous task", exact:true}).click();
    await page.getByRole("button", {name:"Allow once", exact:true}).click();
    await page.locator('[data-task-status="awaiting_approval"]').waitFor({timeout:60000});
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
    await page.getByRole("button", {name:"Task", exact:true}).click();

    for (const panel of ["Task", "Context", "Git", "Plan", "Diagnostics"]) {
      await page.getByRole("button", {name: panel, exact: true}).click();
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
    await page.getByRole("button", {name: "Diagnostics", exact: true}).click();
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
    await page.evaluate(ids => window.localAgent.planRequest(ids.thread, "plan.step.update", {plan_id: ids.plan, step_id: ids.step, state: "skipped"}), blockedPlan);
    checks.push("Failed send preserves draft");

    await page.locator(".composer textarea").fill("slow-stream");
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".stop-button").click();
    await page.locator(".send-button").waitFor({state: "visible"});
    checks.push("Stop cancels an active provider stream");

    await page.getByRole("button", {name: "New thread", exact: true}).click();
    await page.locator(".composer textarea").fill("A fresh thread can send messages");
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".message.agent h3").waitFor();
    await page.locator(".send-button").waitFor({state: "visible"});
    await page.locator(".thread-item.active").click({button: "right"});
    await page.locator("#thread-rename-input").fill("验收会话");
    await page.locator("#thread-rename-input").press("Enter");
    await page.getByRole("button", {name: "验收会话", exact: true}).waitFor();
    checks.push("New thread sends; right-click rename persists");

    await screenshot("desktop-dark.png");
    await page.getByRole("button", {name: "Toggle color theme"}).click();
    await screenshot("desktop-light.png");
    for (const width of [1180, 900]) {
      await application.evaluate(({BrowserWindow}, width) => BrowserWindow.getAllWindows()[0].setSize(width, 780), width);
      await page.getByRole("button", {name: "Context", exact: true}).click();
      await page.locator(".context-overlay").waitFor({state: "visible"});
      await screenshot(`desktop-context-${width}.png`);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Horizontal page overflow");
      await page.getByRole("button", {name: "Context", exact: true}).click();
      await page.locator(".context-overlay").waitFor({state: "hidden"});
    }
    checks.push("Light/dark themes, 1180/900px window sizes and panel layout");
    await application.close();
    page = await launch();
    await page.getByRole("button", {name: "验收会话", exact: true}).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light");
    assert(await page.locator(".message.agent h3").count() > 0);
    checks.push("Restart restores thread, message history, expansion and theme");
    await page.locator(".project-tree-header.active").click();
    await application.close();
    page = await launch();
    assert.equal(await page.locator(".project-tree-header.active").getAttribute("aria-expanded"), "false");
    checks.push("Collapsed project remains collapsed after restart");
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
