export type ExecutionCall = {call_id:string; tool:string; status:string; metadata?:{duration_ms?:number;error_code?:string;diagnosis?:{category:string;summary:string;action:string}}};
export function RecentExecutions({calls}: {calls:ExecutionCall[]}) {
  return <details><summary>最近工具调用与失败诊断</summary>{calls.slice(-30).reverse().map(call => <p key={call.call_id}>
    {call.tool} · {call.status} · {call.metadata?.duration_ms == null ? "耗时未知" : `${call.metadata.duration_ms}ms`} · {call.metadata?.error_code ?? "—"}
    {call.metadata?.diagnosis ? <span> · {call.metadata.diagnosis.category}：{call.metadata.diagnosis.summary} 下一步：{call.metadata.diagnosis.action}</span> : null}
  </p>)}</details>;
}
