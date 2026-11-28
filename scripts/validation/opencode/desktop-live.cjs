/* Real product Electron → OpenCode → existing local Ollama. No model installation. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { randomBytes } = require("node:crypto");
const { _electron } = require("../../../desktop/node_modules/playwright-core");

const root = path.resolve(__dirname, "../../..");
const reports = path.join(root, "validation-reports");
fs.mkdirSync(reports, {recursive:true});
const data = fs.mkdtempSync(path.join(reports, "lca-v2-live-"));
const project = path.join(data, "isolated-project");
fs.mkdirSync(project);
const checks = [];
const model = "qwen3:4b";
const mock = process.argv.includes("--mock");
const dropCompletion = mock && process.argv.includes("--drop-completion");
const projectWrite = mock || process.argv.includes("--project-write");
const outside = path.join(data, "different-project.txt");
const outsideCanary = "EXTERNAL_" + randomBytes(10).toString("hex");
if (mock) fs.writeFileSync(outside,outsideCanary);
const testEnv = Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith("GIT_CONFIG_")));
let outsideResult;
let provider;
let providerUrl = "http://127.0.0.1:11434";
let modelRequests = 0;
let toolRequests = 0;
let nativeShellResult = false;
const started = Date.now();
let application;

async function launch() {
  application = await _electron.launch({
    executablePath: require("../../../desktop/node_modules/electron"),
    args: [path.join(root, "desktop"), "--disable-gpu"],
    cwd: root,
    timeout: 60_000,
    env: {
      ...testEnv, LCA_DATA_DIR: path.join(data, "agent"), LCA_DESKTOP_DATA_DIR: path.join(data, "desktop"),
      LCA_PROVIDER:"ollama", LCA_OLLAMA_URL:providerUrl, LCA_OLLAMA_MODEL:model, LCA_OPENAI_API_KEY:"",
    },
  });
  const page = await application.firstWindow();
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const status = await page.evaluate(() => window.localAgent.getAgentStatus());
    if (status.state === "error") throw new Error(status.error);
    if (status.state === "ready") {
      const reply = await page.evaluate(() => window.localAgent.getProject().catch(() => null));
      if (reply?.type === "project.loaded") return page;
    }
    await new Promise(resolve => setTimeout(resolve,150));
  }
  throw new Error("Data service readiness timeout");
}

async function main() {
  if (mock) {
    fs.writeFileSync(path.join(project,"calculator.py"),"def add(a, b):\n    return a - b\n");
    fs.writeFileSync(path.join(project,"test_calculator.py"),"import unittest\nfrom calculator import add\nclass CalculatorTest(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n");
    fs.writeFileSync(path.join(project,".gitignore"),"__pycache__/\n");
    for (const argv of [["init","-q","-b","main"],["add","."],["-c","user.name=Fixture","-c","user.email=fixture@example.test","commit","-qm","fixture"]]) {
      execFileSync("git",argv,{cwd:project,env:testEnv});
    }
    provider = http.createServer(async (req,res) => {
      if (req.method === "GET" && req.url === "/api/tags") {
        res.writeHead(200,{"Content-Type":"application/json"});
        return res.end(JSON.stringify({models:[{model,name:model}]}));
      }
      if (req.method === "POST" && req.url === "/api/show") {
        res.writeHead(200,{"Content-Type":"application/json"});
        return res.end(JSON.stringify({capabilities:["completion","tools"]}));
      }
      if (req.method !== "POST" || req.url !== "/v1/chat/completions") return res.writeHead(404).end();
      let raw = "";
      for await (const chunk of req) raw += chunk;
      const request = JSON.parse(raw);
      const transcript = JSON.stringify(request.messages);
      const canary = transcript.match(/LCA[a-f0-9]{10}/)?.[0];
      if (request.model !== model || !request.stream) return res.writeHead(400).end();
      modelRequests++;
      res.writeHead(200,{"Content-Type":"text/event-stream"});
      const delta = (content,finish_reason) => "data: "+JSON.stringify({id:"fixture",object:"chat.completion.chunk",model,
        choices:[{index:0,delta:content,finish_reason}]})+"\n\n";
      const user = request.messages.findLastIndex(message => message.role === "user");
      const thisTurn = request.messages.slice(user + 1);
      if (JSON.stringify(request.messages[user] ?? {}).includes("open-code-task-fixture")) {
        const results = thisTurn.filter(message => message.role === "tool");
        if (results.length > 1) {
          nativeShellResult = String(results.at(-1).content).split(/\r?\n/).some(line=>line.trim()==="OPEN_CODE_NATIVE_SHELL_OK");
          return res.end(delta({role:"assistant",content:"Calculator patch submitted for independent verification"},null)+delta({},"stop")+"data: [DONE]\n\n");
        }
        if (results.length === 1) {
          const shellTool = request.tools?.find(tool=>["shell","bash"].includes(tool.function?.name))?.function;
          if (!shellTool?.parameters?.properties?.command) return res.destroy();
          const args = {command:"echo OPEN_CODE_NATIVE_SHELL_OK"};
          if (shellTool.parameters.properties.description) args.description = "Print fixture marker";
          res.write(delta({role:"assistant",tool_calls:[{index:0,id:"call_fixture_task_shell",type:"function",
            function:{name:shellTool.name,arguments:JSON.stringify(args)}}]},null));
          return res.end(delta({},"tool_calls")+"data: [DONE]\n\n");
        }
        const tool = request.tools?.find(tool => tool.function?.name === "write")?.function;
        const field = Object.keys(tool?.parameters?.properties ?? {}).find(name => /^(filePath|path|file_path)$/.test(name));
        if (!field) return res.destroy();
        res.write(delta({role:"assistant",tool_calls:[{index:0,id:"call_fixture_task",type:"function",
          function:{name:"write",arguments:JSON.stringify({[field]:"calculator.py",content:"def add(a, b):\n    return a + b\n"})}}]},null));
        return res.end(delta({},"tool_calls")+"data: [DONE]\n\n");
      }
      if (JSON.stringify(request.messages[user] ?? {}).includes("cross-project-check")) {
        const result = thisTurn.findLast(message => message.role === "tool");
        if (result) {
          outsideResult = String(result.content);
          return res.end(delta({role:"assistant",content:"Cross-project check finished"},null)+delta({},"stop")+"data: [DONE]\n\n");
        }
        const tool = request.tools?.find(tool => tool.function?.name === "read")?.function;
        const field = Object.keys(tool?.parameters?.properties ?? {}).find(name => /^(filePath|path|file_path)$/.test(name));
        if (!field) return res.destroy();
        res.write(delta({role:"assistant",tool_calls:[{index:0,id:"call_fixture_external",type:"function",
          function:{name:"read",arguments:JSON.stringify({[field]:outside})}}]},null));
        return res.end(delta({},"tool_calls")+"data: [DONE]\n\n");
      }
      if (!canary) return res.destroy();
      if (transcript.includes("v2-tool.txt") && !request.messages.some(message => message.role === "tool")) {
        const write = request.tools?.find(tool => tool.function?.name === "write")?.function;
        const fields = write?.parameters?.properties ?? {};
        const pathField = Object.keys(fields).find(name => /^(filePath|path|file_path)$/.test(name));
        if (!write || !pathField || !fields.content) {
          res.destroy();
          return;
        }
        toolRequests++;
        res.write(delta({role:"assistant",tool_calls:[{index:0,id:"call_fixture_write",type:"function",
          function:{name:write.name,arguments:JSON.stringify({[pathField]:path.join(project,"v2-tool.txt"),content:canary})}}]},null));
        return res.end(delta({},"tool_calls")+"data: [DONE]\n\n");
      }
      res.write(delta({role:"assistant",content:"收到 "},null));
      setTimeout(() => res.end(delta({content:canary},null)+delta({},"stop")+"data: [DONE]\n\n"),100);
    });
    await new Promise(resolve => provider.listen(0,"127.0.0.1",resolve));
    providerUrl = "http://127.0.0.1:"+provider.address().port;
  }
  const page = await launch();
  if (dropCompletion) {
    await application.evaluate((_electron, mainFile) => {
      const requireFromApp = process.getBuiltinModule("node:module").createRequire(mainFile);
      const {EngineEventBridge} = requireFromApp("./engineEventBridge.js");
      const follow = EngineEventBridge.prototype.follow;
      EngineEventBridge.prototype.follow = function (sessionId, signal, receive) {
        return follow.call(this,sessionId,signal,event => {
          if (event.kind !== "text" && event.kind !== "execution-ended") receive(event);
        });
      };
    },path.join(root,"desktop","dist-electron","main.js"));
  }
  checks.push("Electron connected to isolated data service");
  await application.evaluate(({dialog}, folder) => {
    dialog.showOpenDialog = async () => ({canceled:false, filePaths:[folder]});
  }, project);
  await page.evaluate(model => window.localAgent.openProject(model), model);
  await page.locator(".composer textarea").waitFor();
  await page.evaluate(() => {
    window.openc = [];
    window.localAgent.onAgentEvent(e => {
      if (e.type.startsWith("turn.") || e.type.startsWith("tool.")) {
        window.openc.push({type:e.type,engine:e.payload?.engine, message:e.type==="turn.failed"?e.payload?.message:undefined});
      }
      if (e.type === "approval.requested") {
        window.openc.push({type:e.type});
        const allowedEdit = e.payload?.tool === "edit" && /v2-tool\.txt|calculator\.py/.test(JSON.stringify(e.payload?.arguments));
        const ownedWorktree = e.payload?.tool === "git_worktree_create" && /^task-/.test(e.payload?.arguments?.task_name ?? "");
        const fixtureShell = ["shell","bash"].includes(e.payload?.tool) &&
          e.payload?.arguments?.resources?.length === 1 && e.payload.arguments.resources[0] === "echo OPEN_CODE_NATIVE_SHELL_OK";
        if (allowedEdit || ownedWorktree || fixtureShell) {
          void window.localAgent.respondApproval(e.payload.approval_id,"allow_once",e.turn_id).catch(error =>
            window.openc.push({type:"approval.error",message:String(error)}));
        }
      }
      if (e.type === "task.updated") window.openc.push({type:e.type,task:e.payload?.task});
    });
  });
  const canary = "LCA" + randomBytes(5).toString("hex");
  const input = page.locator(".composer textarea");
  await input.fill(projectWrite ? "请用 write 工具在当前工程创建一个文件 v2-tool.txt，只写入这一行：" + canary +
    "。必须成功写入后再回复「收到 " + canary + "」。" :
    "请直接用简体中文回复「收到 " + canary + "」。无需使用工具。");
  await page.waitForFunction(() => document.querySelector(".send-button")?.disabled === false);
  await input.press("Enter");
  await page.waitForFunction(() => window.openc.some(e => ["turn.completed","turn.failed","turn.cancelled"].includes(e.type)), null, {timeout:630_000});
  const events = await page.evaluate(() => window.openc);
  const result = events.find(e => ["turn.completed","turn.failed","turn.cancelled"].includes(e.type));
  assert.equal(result.type, "turn.completed", result.message);
  assert.equal(result.engine, "opencode");
  assert(events.some(e => e.type === "turn.delta"));
  assert((await page.locator(".message.agent").last().innerText()).includes(canary));
  if (projectWrite) {
    if (mock) {
      assert.equal(toolRequests,1,"Mock must direct one native file write");
      assert(modelRequests >= 2,"Native tool output must return to the model");
    }
    assert(events.some(event => event.type === "approval.requested"),"Approval was not emitted by OpenCode");
    assert(events.some(event => event.type === "tool.completed"),"Native tool result was not shown");
    assert.equal(fs.readFileSync(path.join(project,"v2-tool.txt"),"utf8").trim(),canary);
    checks.push("OpenCode native write waited for one-shot approval, then changed the isolated file");
  }
  checks.push(dropCompletion ? "Missing text and terminal SSE were restored from the current native durable completion" :
    mock ? "Official composer streamed through OpenCode and the non-default-port model mock" :
    "Official composer streamed a real OpenCode answer via qwen3:4b");
  if (mock) {
    await page.evaluate(() => {window.openc.length=0;});
    await input.fill("cross-project-check: check the fixture outside the open project");
    await page.waitForFunction(() => document.querySelector(".send-button")?.disabled === false);
    await input.press("Enter");
    await page.waitForFunction(() => window.openc.some(e => ["turn.completed","turn.failed"].includes(e.type)), null, {timeout:30_000});
    assert(outsideResult,"Cross-project fixture must receive a native tool response");
    assert(!outsideResult.includes(outsideCanary),"Out-of-project confidential text reached the provider");
    assert.match(outsideResult, /permission|denied|not allowed|outside/i);
    checks.push("OpenCode blocked a read of a sibling file before its contents reached the model");
    const thread = await page.evaluate(async () => (await window.localAgent.getProject()).payload.active_thread.id);
    const taskID = await page.evaluate(async threadId => {
      const prepared = await window.localAgent.taskRequest(threadId,"task.start",{goal:"open-code-task-fixture: repair calculator.py",config:{verification_commands:["python -m unittest discover -v"]}});
      return prepared.payload.task.id;
    },thread);
    await page.waitForFunction(id => window.openc.some(e => e.type === "task.updated" && e.task?.id === id),taskID,{timeout:60_000});
    const task = await page.evaluate(id => window.openc.find(e => e.type === "task.updated" && e.task?.id === id).task,taskID);
    const failures = await page.evaluate(() => window.openc.filter(e=>e.type === "turn.failed").map(e=>e.message));
    assert.equal(task.status,"awaiting_approval",JSON.stringify({reason:task.reason,verification:task.verification,failures}));
    assert.notEqual(task.workspace,project);
    assert(task.verification.every(result=>result.ok));
    assert(task.report.diff.includes("return a + b"));
    assert(fs.readFileSync(path.join(project,"calculator.py"),"utf8").includes("return a - b"));
    assert(nativeShellResult,"Native shell stdout must be returned to the model after one-shot approval");
    checks.push("Official Task used isolated Git, native file write and shell, independent unittest and verified Git diff");
  }
  await application.close();
  application = undefined;
  const restarted = await launch();
  await restarted.locator(".message.agent").filter({hasText:canary}).waitFor();
  checks.push("Assistant message persisted across Electron restart");
}

main().then(() => write("PASS"), error => {
  write("FAIL", error.message);
  process.exitCode = 1;
}).finally(async () => {
  if (application) await application.close();
  if (provider) await new Promise(resolve => {provider.close(resolve);provider.closeAllConnections();});
});

function write(status, error) {
  const report = {status, model, mock, drop_completion:dropCompletion, checks, error, elapsed_ms:Date.now()-started, evidence_dir:data};
  const destination = path.join(reports, dropCompletion ? "v2-opencode-desktop-recovery.json" : mock ? "v2-opencode-desktop-mock.json" : projectWrite ? "v2-opencode-desktop-live-tool.json" : "v2-opencode-desktop-live.json");
  fs.mkdirSync(path.dirname(destination), {recursive:true});
  fs.writeFileSync(destination, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
}
