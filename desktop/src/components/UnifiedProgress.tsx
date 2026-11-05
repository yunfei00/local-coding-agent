import {useEffect,useState} from 'react';
import type {TaskVerification} from '../lib/autonomousTask';
export type UnifiedRun = {
  id:string;revision?:number;plan_id?:string;recovery_plan_id?:string;intent:string;phase:string;outcome?:string;reason?:string;error_code?:string;
  level:string;changed_paths:string[];verification:TaskVerification[];model?:string;provider?:string;
  diagnostic_checks?:Array<{command:string;exit_code:number;summary:string}>;
  knowledge_warning?:string;
  usage?:{api_calls:number;reserved_tokens:number;input_tokens:number;output_tokens:number;estimated:boolean};
  routing?:{mode?:string;current?:string;reason?:string[];switches?:Array<{from:string;to:string;code:string}>};
  context_state?:{compressed:boolean;recovered:boolean;memory_hits:number;retrieval_hits:number;index_version?:number};
  execution_limits?:{tool_calls:number;max_tool_calls:number;stage_reserved_tokens:Record<string,number>;max_stage_tokens:number;elapsed_seconds:number};
  current_role?:string;
  workflow_progress?:{completed:number;total:number;percent:number;blocked:string[]};
  role_handoffs?:Array<{step_id:string;role:string;model:string;provider:string;sequence:number}>;
  plan?:{steps:Array<{id:string;description:string;state:string;workflow?:{assigned_role?:string;dependencies?:string[];acceptance_criteria?:string[]}} >};
};
const labels:Record<string,string>={question:'问答',analysis:'分析项目',interaction:'操作桌面',change:'修改代码',complex:'执行开发计划',executing:'执行中',verifying:'独立验证中',repairing:'修复验证失败',completed_verified:'已完成 · 验证通过',completed_unverified:'开发完成 · 尚未验证',partially_completed:'部分完成',awaiting_user:'等待处理 · 验证受阻',cancelled:'已取消',failed:'执行失败',paused:'已暂停'};
export function useUnifiedProgress(thread:string,ready:boolean) {
  const [run,setRun]=useState<UnifiedRun>();
  useEffect(()=>{
    let alive=true;setRun(undefined);
    if(!thread || !ready)return;
    const apply=(value:UnifiedRun|undefined)=>setRun(current=>current && value?.id===current.id && (current.revision || 0)>(value.revision || 0)?current:value);
    const reload=()=>{void window.localAgent.taskRequest(thread,'task.runtime.list').then(event=>{if(alive)apply((event.payload?.runtimes as UnifiedRun[]|undefined)?.[0]);}).catch(()=>{});};
    reload();
    const unsubscribe=window.localAgent.onAgentEvent(event=>{
      if(event.type==='connection.restored')reload();
      if(event.thread_id===thread && ['plan.loaded','plan.step.completed','plan.completed'].includes(event.type))reload();
      if(event.thread_id===thread && event.type==='agent.runtime.updated' && alive)apply(event.payload?.runtime as UnifiedRun);
      if(event.thread_id===thread && ['turn.completed','turn.failed','turn.cancelled'].includes(event.type))reload();
    });
    return()=>{alive=false;unsubscribe();};
  },[thread,ready]);
  return run;
}
export function UnifiedProgress({run,onResume,onDiagnostics,onExport,onPlan}:{run:UnifiedRun;onResume:()=>void;onDiagnostics:()=>void;onExport?:()=>Promise<Record<string,unknown>>;onPlan?:()=>void}){
  const [diagnostic,setDiagnostic]=useState<Record<string,unknown>>();
  useEffect(()=>setDiagnostic(undefined),[run.id]);
  if(run.intent==='question' && !run.changed_paths.length && run.phase==='completed' && !run.routing?.switches?.length)return null;
  return <section className="context-section conversation-task" aria-label="Agent 执行结果">
    <strong>{run.phase==='completed' && run.intent==='interaction' && run.outcome==='completed_unverified' ? '桌面操作已结束 · 待独立验收' : run.phase==='completed' && !run.changed_paths.length ? '已完成 · 未修改文件，无需代码验证' : run.outcome ? labels[run.outcome] || run.outcome : `${labels[run.intent] || run.intent} · ${labels[run.phase] || run.phase}`}</strong>
    {run.reason?<p>{run.reason}</p>:null}
    {run.knowledge_warning?<p>{run.knowledge_warning}</p>:null}
    {run.routing?.mode?<details><summary>{run.routing.mode==='auto'?'自动选择模型':'手动选择模型'} · 当前 {run.model}</summary><p>{run.routing.reason?.join('；')}</p>{run.routing.switches?.map((s,i)=><p key={i}>{s.from} → {s.to}：{s.code}</p>)}</details>:null}
    {run.context_state?<p>项目记忆命中 {run.context_state.memory_hits} · 工程检索 {run.context_state.retrieval_hits} · {run.context_state.compressed?'上下文已压缩':'上下文未压缩'} · {run.context_state.recovered?'已恢复原执行状态':'新运行'}</p>:null}
    {run.execution_limits?<details><summary>预算与连续执行</summary><p>工具 {run.execution_limits.tool_calls} / {run.execution_limits.max_tool_calls} · 累计 {run.execution_limits.elapsed_seconds} 秒</p><p>阶段 Token 保守预留（不是实际计费）：{Object.entries(run.execution_limits.stage_reserved_tokens).map(([phase,tokens])=>`${phase} ${tokens}`).join('；')} · 每阶段上限 {run.execution_limits.max_stage_tokens}</p></details>:null}
    {run.usage?<p>{run.provider} / {run.model} · API {run.usage.api_calls} · Token 用量/保守预留 {run.usage.reserved_tokens}{run.usage.estimated?'（含估算）':''}</p>:null}
    {run.changed_paths.length?<details><summary>修改了 {run.changed_paths.length} 个文件 · 验证级别 {run.level}</summary><ul>{run.changed_paths.map(p=><li key={p}>{p}</li>)}</ul></details>:null}
    {run.diagnostic_checks?.map((r,i)=><details key={`diagnostic-${i}`}><summary>只读诊断 · {r.command} · exit {r.exit_code}</summary><p>该失败用于分析原因，不代表测试通过。</p><pre style={{whiteSpace:'pre-wrap'}}>{r.summary}</pre></details>)}
    {run.verification.map((r,i)=><details key={i}><summary>{r.ok?'通过':'未通过'} · {r.command} · exit {r.exit_code ?? '未执行'}</summary><p>{r.category} · {r.duration_ms} ms</p><pre style={{whiteSpace:'pre-wrap'}}>{r.summary}</pre><p>日志：{r.log_path}</p></details>)}
    {run.intent==='complex' && run.plan?<details open><summary>持久化计划{run.workflow_progress?` · ${run.workflow_progress.completed}/${run.workflow_progress.total} (${run.workflow_progress.percent}%)`:''}{run.current_role?` · ${run.current_role}`:''}</summary><ol>{run.plan.steps.map(s=><li key={s.id}>{s.description} — {s.state}{s.workflow?.assigned_role?` · ${s.workflow.assigned_role}`:''}{s.workflow?.dependencies?.length?<small> · 依赖 {s.workflow.dependencies.join('、')}</small>:null}{s.workflow?.acceptance_criteria?.length?<details><summary>验收要求</summary>{s.workflow.acceptance_criteria.join('；')}</details>:null}</li>)}</ol>{run.role_handoffs?.length?<details><summary>角色交接记录</summary><ol>{run.role_handoffs.map(h=><li key={h.sequence}>{h.role} · {h.provider} / {h.model}</li>)}</ol></details>:null}</details>:null}
    {['failed','paused','cancelled'].includes(run.phase)?<button type="button" onClick={onResume}>{run.recovery_plan_id || run.plan_id ? '检查并继续未完成步骤':'检查并恢复原运行'}</button>:null}
    {run.error_code==='PLAN_UNCERTAIN_EFFECTS'&&onPlan?<button type="button" onClick={onPlan}>核对中断操作</button>:null}
    <button type="button" onClick={()=>onExport ? void onExport().then(setDiagnostic).catch(error=>setDiagnostic({markdown:String(error)})) : onDiagnostics()}>查看当前诊断</button>
    {diagnostic?<details open><summary>当前诊断快照</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{String(diagnostic.markdown || '')}</pre><p>完整历史 JSON：{String(diagnostic.json_path || '')}</p><button type="button" onClick={()=>void window.localAgent.copyText(String(diagnostic.markdown || ''))}>复制诊断</button></details>:null}
  </section>;
}
