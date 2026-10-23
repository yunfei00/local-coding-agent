export function ModelDiagnosticResult({report}: {report: Record<string, unknown>}) {
  const status = (key:string) => ["PASS","FAIL","NOT RUN"].includes(String(report[key])) ? String(report[key]) : "NOT RUN";
  return <div role="status"><p>配置 {status("configuration")} · 连接 {status("connection")} · 文本 {status("text")} · 视觉 {status("vision")} · 工具 {status("tools")}</p><details open><summary>测试结果与错误详情</summary><pre>{JSON.stringify(report,null,2)}</pre></details></div>;
}
