/* Real product Electron → OpenCode → existing local Ollama. No model installation. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
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
const online = process.argv.find(arg => arg.startsWith("--online="))?.slice(9);
if (online !== undefined && !["kimi-k3.1-pro","qwen4-max"].includes(online)) {
  throw new Error("Select an explicitly authorized saved online model");
}
const model = online ?? "qwen3:4b";
const mock = process.argv.includes("--mock");
if (online && mock) throw new Error("Choose mock or online");
const dropCompletion = mock && process.argv.includes("--drop-completion");
const dropText = dropCompletion || (mock && process.argv.includes("--drop-text"));
const projectWrite = mock || process.argv.includes("--project-write");
const liveTask = !mock && (online || process.argv.includes("--project-task"));
const tunedOrigin = !mock && process.env.LCA_TEST_OLLAMA_ORIGIN;
const outside = path.join(data, "different-project.txt");
const outsideCanary = "EXTERNAL_" + randomBytes(10).toString("hex");
if (mock) fs.writeFileSync(outside,outsideCanary);
const testEnv = Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith("GIT_CONFIG_")));
let outsideResult;
let provider;
let providerUrl = "http://127.0.0.1:11434";
if (tunedOrigin) {
  const origin = new URL(tunedOrigin);
  if (origin.protocol !== "http:" || origin.hostname !== "127.0.0.1" || origin.username || origin.password ||
      origin.pathname !== "/" || origin.search || origin.hash) throw new Error("The alternate Ollama test service must be on HTTP loopback");
  providerUrl = origin.origin;
}
let modelRequests = 0;
let toolRequests = 0;
let nativeShellResult = false;
let resumedPlan;
const started = Date.now();
let application;
let onlineProfile;
let onlineState;
const usage = new Map();

function seedOnlineProfile() {
  const source = path.join(testEnv.APPDATA, "local-coding-agent-desktop");
  onlineState = fs.mkdtempSync(path.join(os.tmpdir(),"lca-online-"));
  const desktopData = path.join(onlineState,"desktop");
  fs.mkdirSync(desktopData);
  const seed = `
import contextlib, json, pathlib, sqlite3, sys
from agent.persistence.store import SQLiteStore
from agent.llm.router import validate_config
source, dest, model = sys.argv[1:]
with contextlib.closing(sqlite3.connect((pathlib.Path(source) / "local-coding-agent.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
    raw = db.execute("SELECT value FROM settings WHERE key=?", ("models.catalog.v1",)).fetchone()
catalog = json.loads(raw[0]) if raw else {}
connections = {c["connection_id"]: c for c in catalog.get("connections", []) if c["enabled"] and c["provider_type"] == "openai_compatible"}
profiles = [p for p in catalog.get("profiles", []) if p["model_id"] == model and p["connection_id"] in connections]
if len(profiles) != 1:
    print("NOT_RUN")
    sys.exit(0)
profile = profiles[0]
connection = connections[profile["connection_id"]]
if not connection["base_url"].startswith("https://") or not connection["credential_reference"] or profile.get("tool_mode") == "none":
    print("NOT_RUN")
    sys.exit(0)
profile["max_output_tokens"] = min(profile.get("max_output_tokens") or 1024, 1024)
config = validate_config({"budget": {"api_calls": 8, "global_api_calls": 12, "api_tokens": 2000000, "global_api_tokens": 2000000, "request_seconds": 60, "task_seconds": 240}})
config["roles"]["executor"]["model_profile_id"] = profile["model_profile_id"]
with contextlib.closing(SQLiteStore(dest)) as store:
    store.set_setting("models.catalog.v1", json.dumps({"profiles": [profile], "connections": [connection]}))
    store.set_setting("orchestration.config", json.dumps(config))
    store.set_setting("chat.default_profile_id", profile["model_profile_id"])
print(profile["model_profile_id"] + (" legacy" if connection["credential_reference"] == "legacy-openai" else " protected"))
`;
  const selected = execFileSync("uv",["run","python","-c",seed,source,path.join(onlineState,"agent"),model],{cwd:root,env:testEnv,encoding:"utf8"}).trim();
  if (selected === "NOT_RUN") return false;
  const [profile, type] = selected.split(" ");
  assert.match(profile,/^[A-Za-z0-9_-]{1,100}$/);
  const secretFile = type === "legacy" ? "provider-secrets.json" : "model-secrets.json";
  if (!fs.existsSync(path.join(source,secretFile))) return false;
  fs.copyFileSync(path.join(source,secretFile),path.join(desktopData,secretFile));
  onlineProfile = "profile:"+profile;
  return true;
}

async function launch() {
  application = await _electron.launch({
    executablePath: require("../../../desktop/node_modules/electron"),
    args: [path.join(root, "desktop"), "--disable-gpu"],
    cwd: root,
    timeout: 60_000,
    env: {
      ...testEnv, LCA_DATA_DIR: path.join(onlineState ?? data, "agent"), LCA_DESKTOP_DATA_DIR: path.join(onlineState ?? data, "desktop"),
      LCA_PROVIDER:"ollama", LCA_OLLAMA_URL:providerUrl, LCA_OLLAMA_MODEL:online ? "fixture-never-requested" : model, LCA_OPENAI_API_KEY:"",
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
  if (online && !seedOnlineProfile()) return "NOT_RUN";
  if (mock || liveTask) {
    fs.writeFileSync(path.join(project,"calculator.py"),"def add(a, b):\n    return a - b\n");
    fs.writeFileSync(path.join(project,"test_calculator.py"),"import unittest\nfrom calculator import add\nclass CalculatorTest(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n");
    fs.writeFileSync(path.join(project,".gitignore"),"__pycache__/\n");
    for (const argv of [["init","-q","-b","main"],["add","."],["-c","user.name=Fixture","-c","user.email=fixture@example.test","commit","-qm","fixture"]]) {
      execFileSync("git",argv,{cwd:project,env:testEnv});
    }
  }
  if (mock) {
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
      const requestText = JSON.stringify(request.messages[user] ?? {});
      const thisTurn = request.messages.slice(user + 1);
      if (requestText.includes("RESUME_CHECKPOINT_FIXTURE")) {
        resumedPlan = requestText.includes("Verify saved fixture") && requestText.includes("Already wrote fixture") && requestText.includes("checkpoint_id");
        return res.end(delta({role:"assistant",content:"OPEN_CODE_RESUMED_CHECKPOINT"},null)+delta({},"stop")+"data: [DONE]\n\n");
      }
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
  if (tunedOrigin) {
    await page.evaluate(async () => {
      const api=window.localAgent;
      const saved=(await api.taskRequest("","task.settings.get")).payload.config;
      await api.taskRequest("","task.settings.update",{config:{...saved,budget:{...saved.budget,request_seconds:240,task_seconds:600}}});
    });
  }
  if (dropText) {
    await application.evaluate((_electron, {mainFile,dropCompletion}) => {
      const requireFromApp = process.getBuiltinModule("node:module").createRequire(mainFile);
      const {EngineEventBridge} = requireFromApp("./engineEventBridge.js");
      const follow = EngineEventBridge.prototype.follow;
      EngineEventBridge.prototype.follow = function (sessionId, signal, receive) {
        return follow.call(this,sessionId,signal,event => {
          if (event.kind !== "text" && (!dropCompletion || event.kind !== "execution-ended")) receive(event);
        });
      };
    },{mainFile:path.join(root,"desktop","dist-electron","main.js"),dropCompletion});
  }
  checks.push("Electron connected to isolated data service");
  await application.evaluate(({dialog}, folder) => {
    dialog.showOpenDialog = async () => ({canceled:false, filePaths:[folder]});
  }, project);
  await page.evaluate(model => window.localAgent.openProject(model), onlineProfile ?? model);
  await page.locator(".composer textarea").waitFor();
  await page.exposeFunction("saveGatewayUsage", (turn, count) => usage.set(turn,count));
  await page.evaluate(online => {
    window.openc = [];
    window.localAgent.onAgentEvent(e => {
      if (e.type.startsWith("turn.") || e.type.startsWith("tool.")) {
        window.openc.push({type:e.type,engine:e.payload?.engine,name:e.payload?.name,message:e.type==="turn.failed"?e.payload?.message:undefined});
      }
      if (e.type === "turn.metrics") void window.saveGatewayUsage(e.turn_id,e.payload?.execution_summary?.provider_requests);
      if (e.type === "approval.requested") {
        window.openc.push({type:e.type});
        const allowedEdit = e.payload?.tool === "edit" && /v2-tool\.txt|calculator\.py/.test(JSON.stringify(e.payload?.arguments));
        const ownedWorktree = e.payload?.tool === "git_worktree_create" && /^task-/.test(e.payload?.arguments?.task_name ?? "");
        const fixtureShell = ["shell","bash"].includes(e.payload?.tool) &&
          e.payload?.arguments?.resources?.length === 1 &&
          (online ? /^(python -m unittest( discover)?( -v)?|git (status( --short)?|diff( -- calculator\.py)?))$/.test(e.payload.arguments.resources[0]) :
            e.payload.arguments.resources[0] === "echo OPEN_CODE_NATIVE_SHELL_OK");
        if (allowedEdit || ownedWorktree || fixtureShell) {
          void window.localAgent.respondApproval(e.payload.approval_id,"allow_once",e.turn_id).catch(error =>
            window.openc.push({type:"approval.error",message:String(error)}));
        } else if (online) void window.localAgent.respondApproval(e.payload.approval_id,"deny",e.turn_id);
      }
      if (e.type === "task.updated") window.openc.push({type:e.type,task:e.payload?.task});
    });
  },Boolean(online));
  if (liveTask && !online) {
    await checkTask(page);
    return;
  }
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
    dropText ? "Missing text was restored after the live native terminal event" :
    mock ? "Official composer streamed through OpenCode and the non-default-port model mock" :
    `Official composer streamed a real OpenCode answer via ${model}`);
  if (online) {
    await page.evaluate(() => { window.openc.length=0; });
    await input.fill("请复述本会话上条回复中的验收标记。只回复标记，无需工具。");
    await page.waitForFunction(() => document.querySelector(".send-button")?.disabled === false);
    await input.press("Enter");
    await page.waitForFunction(() => window.openc.some(e => ["turn.completed","turn.failed","turn.cancelled"].includes(e.type)),null,{timeout:120_000});
    const continuation = (await page.evaluate(() => window.openc)).find(e => ["turn.completed","turn.failed","turn.cancelled"].includes(e.type));
    assert.equal(continuation.type,"turn.completed",continuation.message);
    await page.locator(".message.agent").last().filter({hasText:canary}).waitFor();
    checks.push("Online multi-turn reply recovered the previous message's canary");
    await checkTask(page);
  }
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
    await checkTask(page);
  }
  const plan = mock && !dropText ? await page.evaluate(async () => {
    const api = window.localAgent;
    const threadId = (await api.getProject()).payload.active_thread.id;
    const created = (await api.planRequest(threadId,"plan.create",{
      goal:"RESUME_CHECKPOINT_FIXTURE",
      steps:[{description:"Already wrote fixture"},{description:"Verify saved fixture"}],
    })).payload.plans.find(plan=>plan.goal==="RESUME_CHECKPOINT_FIXTURE");
    await api.planRequest(threadId,"plan.step.update",{plan_id:created.id,step_id:created.steps[0].id,state:"skipped"});
    await api.planRequest(threadId,"plan.checkpoint",{plan_id:created.id});
    return {id:created.id,threadId};
  }) : undefined;
  await application.close();
  application = undefined;
  const restarted = await launch();
  await restarted.locator(".message.agent").filter({hasText:canary}).waitFor();
  checks.push("Assistant message persisted across Electron restart");
  if (plan) {
    const fixture = path.join(project,"v2-tool.txt");
    const written = fs.statSync(fixture).mtimeMs;
    const before = modelRequests;
    const outcome = await restarted.evaluate(async ({threadId,id,model}) => {
      const api = window.localAgent;
      window.resumeEvents = [];
      api.onAgentEvent(event => {
        if (["turn.completed","turn.failed","turn.cancelled"].includes(event.type)) {
          window.resumeEvents.push({type:event.type,message:event.payload?.message});
        }
      });
      try {
        await api.startTurn(threadId,"Check the checkpoint",model,true,{run_id:"not-the-owned-plan",confirm_workspace:true});
        return "unexpected admission";
      } catch {
        const turn = await api.startTurn(threadId,"Check the checkpoint",model,true,{run_id:id,confirm_workspace:true});
        return turn.payload?.engine;
      }
    },{...plan,model:await restarted.locator(".model-select").inputValue()});
    assert.equal(outcome,"opencode");
    await restarted.waitForFunction(() => window.resumeEvents.length > 0);
    const terminal = await restarted.evaluate(() => window.resumeEvents[0]);
    assert.equal(terminal.type,"turn.completed",terminal.message);
    await restarted.locator(".message.agent").filter({hasText:"OPEN_CODE_RESUMED_CHECKPOINT"}).waitFor();
    assert.equal(modelRequests-before,1,"Only the verified checkpoint was admitted");
    assert(resumedPlan,"The model must receive the saved goal, next step and finished steps");
    assert.equal(fs.statSync(fixture).mtimeMs,written);
    checks.push("Restart resumed the verified checkpoint with OpenCode and left the earlier file write untouched");
  }
}

async function checkTask(page) {
  const thread = await page.evaluate(async model => {
    const session = await window.localAgent.getProject();
    return session.payload.active_thread?.id ?? (await window.localAgent.createThread(model)).payload.thread.id;
  },onlineProfile ?? model);
  const goal = liveTask
    ? "请搜索当前工作树中的 Python 文件，读取 calculator.py 和测试文件。通过 python -m unittest discover -v 复现失败，修复 add，使测试通过，然后重新运行同一命令并检查 git diff。请只编辑 calculator.py，保留测试预期。程序也会独立运行测试和检查 Git Diff。"
    : "open-code-task-fixture: repair calculator.py";
  const taskID = await page.evaluate(async ({threadId,goal,tuned}) => {
    const config={verification_commands:["python -m unittest discover -v"]};
    if (tuned) config.budget={request_seconds:240,task_seconds:600};
    const prepared = await window.localAgent.taskRequest(threadId,"task.start",{goal,config});
    return prepared.payload.task.id;
  },{threadId:thread,goal,tuned:Boolean(tunedOrigin)});
  await page.waitForFunction(id => window.openc.some(e => e.type === "task.updated" && e.task?.id === id),taskID,{timeout:liveTask ? 660_000 : 60_000});
  const events = await page.evaluate(() => window.openc);
  const task = events.find(e => e.type === "task.updated" && e.task?.id === taskID).task;
  const failures = events.filter(e=>e.type === "turn.failed").map(e=>e.message);
  assert.equal(task.status,"awaiting_approval",JSON.stringify({reason:task.reason,verification:task.verification,failures}));
  assert.notEqual(task.workspace,project);
  assert(task.verification.length>0 && task.verification.every(result=>result.ok));
  assert.match(task.report.diff,/return\s+a\s*\+\s*b/);
  assert(fs.readFileSync(path.join(project,"calculator.py"),"utf8").includes("return a - b"));
  if (liveTask) {
    assert(events.some(e => e.type === "tool.requested" && e.name === "read"),"The local model must perform an actual source read");
    checks.push(`Real ${model} read and fixed source in the official isolated Task; independent unittest and Git diff passed`);
  } else {
    assert(nativeShellResult,"Native shell stdout must be returned to the model after one-shot approval");
    checks.push("Official Task used isolated Git, native file write and shell, independent unittest and verified Git diff");
  }
}

main().then(status => write(status ?? "PASS"), error => {
  if (online && ![...usage.values()].some(count=>count>0) &&
      /Cannot decrypt model credentials|Protected model credentials unavailable/.test(error.message)) {
    write("NOT_RUN","Windows protected model credentials could not be read");
    return;
  }
  write("FAIL", error.message);
  process.exitCode = 1;
}).finally(async () => {
  if (application) await application.close();
  if (provider) await new Promise(resolve => {provider.close(resolve);provider.closeAllConnections();});
  if (onlineState) fs.rmSync(onlineState,{recursive:true,force:true});
});

function write(status, error) {
  const requests = [...usage.values()].reduce((sum,count)=>sum+(count??0),0);
  const report = {status, model, mock, drop_completion:dropCompletion, drop_text:dropText, checks,
    diagnostic:error ?? (status === "NOT_RUN" ? "No unique, enabled HTTPS profile with the exact authorized model and a protected credential reference" : undefined),
    elapsed_ms:Date.now()-started, evidence_dir:data,
    ...(online ? {provider_requests:requests,token_usage:status==="NOT_RUN"?0:"UNKNOWN",cost:status==="NOT_RUN"?0:"UNKNOWN"} : {})};
  const destination = path.join(reports, online ? `v2-opencode-online-${online}.json` : dropCompletion ? "v2-opencode-desktop-recovery.json" :
    dropText ? "v2-opencode-desktop-text-recovery.json" : mock ? "v2-opencode-desktop-mock.json" :
    liveTask ? "v2-opencode-desktop-live-task.json" : tunedOrigin ? "v2-opencode-desktop-alternate-ollama.json" :
    projectWrite ? "v2-opencode-desktop-live-tool.json" : "v2-opencode-desktop-live.json");
  fs.mkdirSync(path.dirname(destination), {recursive:true});
  fs.writeFileSync(destination, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
}
