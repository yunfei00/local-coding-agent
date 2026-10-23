import {describe, it, expect} from "vitest";
import {renderToStaticMarkup} from "react-dom/server";
import {RecentExecutions, type ExecutionCall} from "./RecentExecutions";

describe("persistent tool diagnostics", () => {
  it("shows newest tool, bounded history, duration and actionable safe failures", () => {
    const calls: ExecutionCall[] = Array.from({length:35},(_,i)=>({call_id:String(i),tool:`probe_${i}`,status:"succeeded"}));
    calls.push({call_id:"failure",tool:"desktop_inspect",status:"failed",metadata:{duration_ms:123,error_code:"DESKTOP_WINDOW_STALE",diagnosis:{category:"environment",summary:"重新发现窗口",action:"rediscover_windows"}}});
    const html=renderToStaticMarkup(<RecentExecutions calls={calls}/>);
    expect(html).toContain("DESKTOP_WINDOW_STALE");
    expect(html).toContain("123ms");
    expect(html).toContain("rediscover_windows");
    expect(html).not.toContain("probe_0 ·");
    expect(html.indexOf("desktop_inspect")).toBeLessThan(html.indexOf("probe_34"));
  });
});
