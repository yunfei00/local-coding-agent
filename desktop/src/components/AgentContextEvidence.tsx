export type ToolFact = {sequence:number; tool:string; ok:boolean; path?:string; exit_code?:number; error_code?:string};
export type WorkingMemory = {sequence:number; changed_paths:string[]; recent:ToolFact[]; last_command?:ToolFact};
export function AgentContextEvidence({memory, instructions = []}: {
  memory?:WorkingMemory; instructions?:Array<{path:string; sha256:string}>;
}) {
  if (!memory && !instructions.length) return null;
  return <details className="agent-context-evidence">
    <summary>执行上下文 · 工具结果 {memory?.sequence ?? 0} 次 · 仓库指令 {instructions.length} 份</summary>
    <p>记录随 Checkpoint 保留。以下是历史工具事实，不代表当前文件已通过验证；恢复后仍需检查实际文件和重新测试。</p>
    {instructions.length ? <ul aria-label="已加载的仓库指令">{instructions.map(source => <li key={source.path} title={source.sha256}>{source.path}</li>)}</ul> : null}
    {memory?.changed_paths.length ? <p>最近修改路径：{memory.changed_paths.join("、")}</p> : null}
    {memory?.last_command ? <p>最近命令结果：{memory.last_command.ok ? "成功" : "失败"} · Exit {memory.last_command.exit_code ?? "未知"}（历史）</p> : null}
    {memory?.recent.length ? <ol aria-label="保留的工具事实">{memory.recent.slice(-8).map(fact => <li key={fact.sequence}>
      {fact.sequence}. {fact.tool} · {fact.ok ? "成功" : "失败"}{fact.path ? ` · ${fact.path}` : ""}{fact.error_code ? ` · ${fact.error_code}` : ""}
    </li>)}</ol> : null}
  </details>;
}
