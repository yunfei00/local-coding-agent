import {describe,expect,it} from "vitest";
import {renderToStaticMarkup} from "react-dom/server";
import {ModelDiagnosticResult} from "./ModelDiagnosticResult";

describe("model diagnostic capability evidence", () => {
  it("never promotes missing or unrun stages to PASS", () => {
    const html=renderToStaticMarkup(<ModelDiagnosticResult report={{configuration:"PASS",text:"NOT RUN"}} />);
    expect(html).toContain("文本 NOT RUN"); expect(html).toContain("视觉 NOT RUN"); expect(html).toContain("工具 NOT RUN");
  });
  it("shows image assertion failure independently of successful transport", () => {
    const html=renderToStaticMarkup(<ModelDiagnosticResult report={{connection:"PASS",text:"PASS",vision:"FAIL",tools:"PASS",model_id:"selected-visual",cost:null,errors:[{code:"CAPABILITY_ASSERTION_FAILED"}]}} />);
    for (const text of ["连接 PASS","视觉 FAIL","selected-visual","CAPABILITY_ASSERTION_FAILED"]) expect(html).toContain(text);
  });
});
