import {describe, it, expect} from "vitest";
import {renderToStaticMarkup} from "react-dom/server";
import {AgentContextEvidence} from "./AgentContextEvidence";

describe("agent context evidence", () => {
  it("is absent for legacy plans without continuity metadata", () => {
    expect(renderToStaticMarkup(<AgentContextEvidence/>)).toBe("");
  });
  it("exposes scoped source identity and real historical failure without claiming verification", () => {
    const html = renderToStaticMarkup(<AgentContextEvidence instructions={[{path:"src/AGENTS.md",sha256:"source-hash"}]}
      memory={{sequence:40,changed_paths:["calculator.py"],last_command:{sequence:40,tool:"run_command",ok:false,exit_code:1},
        recent:Array.from({length:16},(_,i)=>({sequence:i+25,tool:`tool_${i}`,ok:false,error_code:"COMMAND_FAILED"}))}}/>);
    expect(html).toContain("src/AGENTS.md");
    expect(html).toContain("source-hash");
    expect(html).toContain("工具结果 40 次");
    expect(html).toContain("失败 · Exit 1（历史）");
    expect(html).toContain("不代表当前文件已通过验证");
    expect(html).toContain("calculator.py");
    expect(html).not.toContain("tool_0 ·");
    expect(html).not.toContain("<details class=\"agent-context-evidence\" open");
  });
});
