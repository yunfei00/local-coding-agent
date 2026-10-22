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
    await application.evaluate(({dialog}, {folder,parent}) => {
      dialog.showOpenDialog = async options => ({canceled:false, filePaths:[options.title === "Choose project location" ? parent : folder]});
    }, {folder:project, parent:data});
    await page.evaluate(() => window.localAgent.openProject("smoke-coder"));
    await page.locator(".composer textarea").waitFor({state: "visible"});
    await page.waitForFunction(() => !document.querySelector(".composer textarea").disabled);
    checks.push("Renderer connects to isolated Python Agent and opens project");

    assert.equal(await page.locator(".composer textarea").evaluate(e => getComputedStyle(e).fontSize), "16px");
    assert.equal(await page.locator(".project-tree-name").first().evaluate(e => getComputedStyle(e).fontSize), "14px");
    assert.equal(await page.getByRole("button",{name:"Settings",exact:true}).evaluate(e => getComputedStyle(e).fontSize), "14px");
    checks.push("Readable shared typography: 16px composer, 14px sidebar and controls");
    await page.getByRole("button", {name:"New project",exact:true}).click();
    let projectDialog = page.getByRole("dialog",{name:"New project",exact:true});
    await projectDialog.waitFor();
    await page.getByLabel("Project name",{exact:true}).fill("do-not-create");
    await page.getByLabel("Project name",{exact:true}).press("Escape");
    await projectDialog.waitFor({state:"hidden"});
    assert(!fs.existsSync(path.join(data,"do-not-create")));
    await page.getByRole("button", {name:"New project",exact:true}).click();
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
    await page.getByRole("button",{name:/ui-created-project/}).first().waitFor();
    assert(fs.existsSync(path.join(data,"ui-created-project",".git")));
    const newSession = await page.evaluate(() => window.localAgent.getProject());
    assert.equal(fs.realpathSync.native(newSession.payload.project.path), fs.realpathSync.native(path.join(data,"ui-created-project")));
    await page.getByRole("button",{name:"Open project",exact:true}).click();
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
    await page.waitForFunction(() => document.querySelector('.model-select')?.value === "gpt-oss:20b");
    assert.equal((await page.evaluate(() => window.localAgent.getProject())).payload.active_thread.active_model, "DeepSeek-V4-Flash-SaaS");
    const requestsBeforeChat = modelRequests.length;
    await page.locator(".composer textarea").fill("Check restored local chat model");
    await page.locator(".composer textarea").press("Enter");
    await page.locator(".execution-summary").waitFor();
    await page.locator(".send-button").waitFor({state:"visible"});
    assert.deepEqual(modelRequests.slice(requestsBeforeChat), [{url:"/api/chat",model:"gpt-oss:20b"}]);
    assert.equal((await page.evaluate(() => window.localAgent.getProject())).payload.active_thread.active_model, "gpt-oss:20b");
    await application.close();
    page = await launch();
    await page.waitForFunction(() => document.querySelector('.model-select')?.value === "gpt-oss:20b");
    assert.equal((await page.evaluate(() => window.localAgent.getProject())).payload.active_thread.active_model, "gpt-oss:20b");
    await page.evaluate(settings => window.localAgent.applySettings(settings), previousSettings);
    await application.close();
    page = await launch();
    await page.waitForFunction(() => document.querySelector('.model-select')?.value === "smoke-coder");
    checks.push("Restored API model switches to displayed Ollama model in actual HTTP request; selected model and chat history survive restart");
    await page.locator(".thread-item.active").click();
    await page.waitForFunction(() => document.querySelector('.model-select')?.value === "gpt-oss:20b");
    assert((await page.getByLabel("Chat model",{exact:true}).locator("option:checked").innerText()).includes("unavailable"));
    assert(await page.locator(".send-button").isDisabled());
    await page.getByLabel("Chat model",{exact:true}).selectOption("smoke-coder");
    await page.waitForFunction(() => !document.querySelector('.composer textarea').disabled);
    checks.push("Unavailable saved model is shown explicitly and blocks Send until a valid model is selected");

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
    await page.getByRole("button", {name:"Settings", exact:true}).click();
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
        await page.getByText(/Credential updated:/).waitFor();
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
    for (const [role,name] of Object.entries(roleChoices)) await page.getByLabel(role + " profile", {exact:true}).selectOption(profileIds[name]);
    await page.getByRole("button", {name:"Save model configuration", exact:true}).click();
    await page.getByText("Model configuration saved. Running task snapshots are unchanged.").waitFor();
    await page.getByRole("button", {name:"Test connection / fetch models", exact:true}).click();
    await page.getByRole("button", {name:"Add model: smoke-coder", exact:true}).waitFor();
    await screenshot("desktop-mixed-provider-settings.png");
    const persistedRouting = await page.evaluate(async () => (await window.localAgent.taskRequest("", "task.catalog.get")).payload);
    assert.equal(new Set(Object.values(persistedRouting.config.roles).map(p => p.model_profile_id)).size, 4);
    checks.push("Settings creates local/API connections, four model profiles, distinct role bindings and protected key");
    await application.close();
    page = await launch();
    await page.getByRole("button", {name:"Settings", exact:true}).click();
    await page.getByRole("button", {name:"Models & Routing", exact:true}).click();
    for (const [role,name] of Object.entries(roleChoices)) {
      await page.getByLabel(role + " profile", {exact:true}).waitFor();
      assert.equal(await page.getByLabel(role + " profile", {exact:true}).inputValue(), profileIds[name]);
    }
    await page.getByLabel("Model connection", {exact:true}).selectOption({label:"Company API · openai_compatible"});
    protectedCredentialSeen = false;
    await page.getByRole("button", {name:"Test connection / fetch models", exact:true}).click();
    await page.getByRole("button", {name:"Add model: smoke-coder", exact:true}).waitFor();
    const keyStorage = await page.evaluate(async () => (await window.localAgent.taskRequest("", "task.credential.status")).payload.mode);
    if (keyStorage === "os_protected") {
      assert(protectedCredentialSeen, "Restart lost the protected per-connection key");
      assert(!fs.readFileSync(path.join(data,"desktop","model-secrets.json"),"utf8").includes("mock-only-not-a-real-key"));
    } else skipped.push("OS protected model credentials unavailable; key is session-only as shown in Settings");
    checks.push("Restart restores four distinct role bindings; protected credential reaches the selected API connection");
    await page.getByRole("button", {name:"Settings", exact:true}).click();

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
    await page.waitForTimeout(500);
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

    await page.locator(".sidebar-actions").getByRole("button", {name: "New thread", exact: true}).click();
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
    await page.getByRole("button", {name: "Toggle color theme"}).click();
    await screenshot("desktop-light.png");
    for (const width of [1180, 900]) {
      await application.evaluate(({BrowserWindow}, width) => BrowserWindow.getAllWindows()[0].setSize(width, 780), width);
      await page.getByRole("button", {name: "Context", exact: true}).click();
      await page.locator(".context-overlay").waitFor({state: "visible"});
      await screenshot(`desktop-context-${width}.png`);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Horizontal page overflow");
      assert(await page.locator(".topbar-actions").evaluate(e => e.scrollWidth <= e.clientWidth + 1), "Header controls should wrap instead of requiring horizontal scrolling");
      await page.getByRole("button", {name: "Context", exact: true}).click();
      await page.locator(".context-overlay").waitFor({state: "hidden"});
      await page.getByRole("button",{name:"Settings",exact:true}).click();
      await page.getByRole("button",{name:"Models & Routing",exact:true}).click();
      await page.getByLabel("Connection name",{exact:true}).waitFor();
      assert.equal(await page.getByLabel("Connection name",{exact:true}).evaluate(e => getComputedStyle(e).fontSize),"14px");
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Settings page overflow");
      await screenshot(`desktop-v041-settings-${width}.png`);
      await page.getByRole("button",{name:"Settings",exact:true}).click();
    }
    checks.push("Light/dark themes, 1180/900px window sizes and panel layout");
    await application.close();
    page = await launch();
    await page.getByRole("button", {name: "验收会话", exact: true}).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light");
    assert(await page.locator(".message.agent h3").count() > 0);
    checks.push("Restart restores thread, message history, expansion and theme");
    assert(await page.locator(".project-tree-name").filter({hasText:"ui-created-project"}).count() === 1);
    checks.push("Restart restores the project created through the dialog");
    await page.getByRole("button", {name:"Settings", exact:true}).click();
    await page.getByRole("button", {name:"Models & Routing", exact:true}).click();
    await page.getByLabel("executor profile", {exact:true}).waitFor();
    assert.equal(await page.getByLabel("executor profile", {exact:true}).inputValue(), profileIds["task-executor"]);
    assert.equal(await page.getByLabel("escalation profile", {exact:true}).inputValue(), profileIds["api-escalation"]);
    const afterRestart = await page.evaluate(async () => (await window.localAgent.taskRequest("", "task.catalog.get")).payload.catalog);
    assert.deepEqual(afterRestart, persistedRouting.catalog);
    checks.push("Restart restores multiple connections, model identities and role routing");
    await page.getByRole("button", {name:"Settings", exact:true}).click();
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
