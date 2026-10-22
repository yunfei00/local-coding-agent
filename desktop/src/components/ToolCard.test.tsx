import {describe, it, expect} from "vitest";
import {renderToStaticMarkup} from "react-dom/server";
import {ToolCard} from "./ToolCard";

describe("managed process terminal cards", () => {
  it("shows background server output and process/log identity", () => {
    const html = renderToStaticMarkup(<ToolCard tool={{id:"call", name:"start_process", arguments:{command:"npm run dev"},
      status:"running", pid:1234, processId:"process_owned", logPath:"logs/output.jsonl", shell:"powershell",
      chunks:[{stream:"stdout",sequence:1,text:"SERVER_READY"}]}} />);
    for (const text of ["TERMINAL","SERVER_READY","1234","process_owned","logs/output.jsonl","powershell"])
      expect(html).toContain(text);
  });
  it("keeps a timed-out command and its state visible", () => {
    const html = renderToStaticMarkup(<ToolCard tool={{id:"call",name:"read_process",arguments:{process_id:"owned"},
      status:"stopping",terminationReason:"timeout",chunks:[{stream:"stderr",sequence:2,text:"actual build error"}]}} />);
    expect(html).toContain("TERMINAL");
    expect(html).toContain("timeout");
    expect(html).toContain("actual build error");
  });
});
