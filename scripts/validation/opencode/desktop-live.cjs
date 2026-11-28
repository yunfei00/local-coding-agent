/* Real product Electron → OpenCode → existing local Ollama. No model installation. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
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
const projectWrite = mock || process.argv.includes("--project-write");
let provider;
let providerUrl = "http://127.0.0.1:11434";
let modelRequests = 0;
let toolRequests = 0;
const started = Date.now();
let application;

async function launch() {
  application = await _electron.launch({
    executablePath: require("../../../desktop/node_modules/electron"),
    args: [path.join(root, "desktop"), "--disable-gpu"],
    cwd: root,
    timeout: 60_000,
    env: {
      ...process.env, LCA_DATA_DIR: path.join(data, "agent"), LCA_DESKTOP_DATA_DIR: path.join(data, "desktop"),
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
      if (!canary || request.model !== model || !request.stream) return res.writeHead(400).end();
      modelRequests++;
      res.writeHead(200,{"Content-Type":"text/event-stream"});
      const delta = (content,finish_reason) => "data: "+JSON.stringify({id:"fixture",object:"chat.completion.chunk",model,
        choices:[{index:0,delta:content,finish_reason}]})+"\n\n";
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
        if (e.payload?.tool === "edit" && JSON.stringify(e.payload?.arguments).includes("v2-tool.txt")) {
          void window.localAgent.respondApproval(e.payload.approval_id,"allow_once",e.turn_id).catch(error =>
            window.openc.push({type:"approval.error",message:String(error)}));
        }
      }
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
  checks.push(mock ? "Official composer streamed through OpenCode and the non-default-port model mock" :
    "Official composer streamed a real OpenCode answer via qwen3:4b");
  await application.close();
  application = undefined;
  const restarted = await launch();
  await restarted.locator(".message.agent").last().waitFor();
  assert((await restarted.locator(".message.agent").last().innerText()).includes(canary));
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
  const report = {status, model, mock, checks, error, elapsed_ms:Date.now()-started, evidence_dir:data};
  const destination = path.join(reports, mock ? "v2-opencode-desktop-mock.json" : projectWrite ? "v2-opencode-desktop-live-tool.json" : "v2-opencode-desktop-live.json");
  fs.mkdirSync(path.dirname(destination), {recursive:true});
  fs.writeFileSync(destination, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
}
