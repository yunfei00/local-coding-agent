import {useEffect,useState} from 'react';
import {TaskSnapshot,mergeTaskSnapshot,taskIsActive} from '../lib/autonomousTask';
import {TaskEvidence} from './TaskEvidence';

export function useConversationTasks(threadId:string, ready:boolean) {
  const [tasks,setTasks] = useState<TaskSnapshot[]>([]);
  useEffect(()=>{
    let alive=true; setTasks([]);
    if (!threadId || !ready) return;
    const apply=(event:AgentEnvelope)=>{
      if (!alive) return;
      const task=event.payload?.task as TaskSnapshot|undefined;
      if(task) setTasks(current=>mergeTaskSnapshot(current,task,threadId));
      const list=event.payload?.tasks as TaskSnapshot[]|undefined;
      if(list) setTasks(current=>[...list].reverse().reduce((all,t)=>mergeTaskSnapshot(all,t,threadId),current));
    };
    const load=()=>{void window.localAgent.taskRequest(threadId,'task.list').then(apply).catch(()=>{});};
    load();
    const unsubscribe=window.localAgent.onAgentEvent(event=>{
      if(event.type==='connection.restored') load();
      if(event.thread_id===threadId && ['task.updated','task.loaded'].includes(event.type)) apply(event);
    });
    return ()=>{alive=false;unsubscribe();};
  },[threadId,ready]);
  return {task:tasks[0],active:tasks.find(taskIsActive)};
}

export function ConversationTask({task,onAction,onDetails}:{task:TaskSnapshot;onAction:(operation:string)=>void;onDetails:()=>void}) {
  return <section className="context-section conversation-task" aria-label="对话开发进度" data-conversation-task={task.id}>
    <strong>自主开发 · {task.status}</strong><p>{task.reason}</p>
    <details><summary>需求与追加记录</summary><p>{task.goal}</p></details>
    {task.calls?.length ? <p>当前模型：{task.calls.at(-1)?.role} / {task.calls.at(-1)?.model}</p>:null}
    <p>API {task.usage.api_calls} · Token {task.usage.reserved_tokens} · 工作区 {task.workspace || '等待授权'}</p>
    <TaskEvidence task={task}/>
    <details><summary>计划与验证</summary><ol>{task.plan.steps.map(step=><li key={step.id}>{step.description} — {step.state}</li>)}</ol>
      {task.verification.map((v,i)=><p key={i}>{v.ok?'通过':'失败'} · {v.command} · exit {v.exit_code ?? '未知'} · {v.summary}</p>)}</details>
    {task.report.review ? <details><summary>交付报告与变更</summary><p>{task.report.review}</p><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{task.report.diff}</pre></details>:null}
    {taskIsActive(task) ? <><button type="button" onClick={()=>onAction('task.pause')}>暂停开发</button><button type="button" onClick={()=>onAction('task.cancel')}>停止开发</button></>:
      <button type="button" onClick={()=>onAction('task.resume')}>继续当前开发</button>}
    {task.status==='awaiting_approval' ? <button type="button" onClick={()=>onAction('task.approve')}>接受已验证结果</button>:null}
    <button type="button" onClick={onDetails}>高级配置与诊断</button>
    <p>在下方输入框追加需求，结束或暂停后发送，继续同一隔离工作区；不会自动提交或合并。</p>
  </section>;
}
