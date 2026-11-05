import {useEffect,useState} from 'react';
import {type ModelCatalog,modelLabel} from '../lib/modelCatalog';

type WorkflowConfig={role_models:Record<string,string|null>;max_repairs:number;max_no_progress:number;max_parallel:number};
const roles=[['planner','规划'],['developer','开发'],['reviewer','独立审查'],['tester','测试']];
export function WorkflowSettings({threadId,catalog}:{threadId:string;catalog:ModelCatalog}){
  const [config,setConfig]=useState<WorkflowConfig>();
  const [message,setMessage]=useState('');
  const [templates,setTemplates]=useState<Array<{id:string;name:string;applies_to:string;failure_policy:string}>>([]);
  useEffect(()=>{let alive=true;
    void window.localAgent.taskRequest(threadId,'task.runtime.workflow.get').then(e=>{if(alive)setConfig(e.payload?.workflow as WorkflowConfig);}).catch(e=>{if(alive)setMessage(String(e));});
    void window.localAgent.taskRequest(threadId,'task.runtime.templates').then(e=>{if(alive)setTemplates((e.payload?.templates || []) as typeof templates);}).catch(()=>{});
    return()=>{alive=false;};
  },[threadId]);
  return <details><summary>自主工作流 · 角色与模板</summary><p>默认各角色沿用聊天中选择的模型。独立角色共享原执行账本、权限和项目上下文；新配置仅用于新工作流。</p>
    {config?<><div className="model-settings-grid">{roles.map(([id,name])=><label className="settings-field" key={id}>{name}模型<select aria-label={`${name}角色模型`} value={config.role_models[id] || ''} onChange={e=>setConfig({...config,role_models:{...config.role_models,[id]:e.target.value || null}})}><option value="">沿用聊天模型</option>{catalog.profiles.map(p=><option key={p.model_profile_id} value={p.model_profile_id}>{modelLabel(catalog,p)}</option>)}</select></label>)}
      <label className="settings-field">最大审查修复轮次<input type="number" min={0} max={10} value={config.max_repairs} onChange={e=>setConfig({...config,max_repairs:Number(e.target.value)})}/></label>
      <label className="settings-field">最大无进展轮次<input type="number" min={1} max={10} value={config.max_no_progress} onChange={e=>setConfig({...config,max_no_progress:Number(e.target.value)})}/></label></div>
      <label className="settings-field">并行任务上限<select value={config.max_parallel} onChange={e=>setConfig({...config,max_parallel:Number(e.target.value)})}><option value={1}>1（默认串行）</option><option value={2}>2（仅隔离工作区且内存充足）</option></select></label><p>共享工作树、GUI 焦点或其他资源冲突时串行；并行前至少需要 2.5 GiB 物理内存和提交余量。</p>
      <button type="button" onClick={()=>void window.localAgent.taskRequest(threadId,'task.runtime.workflow.update',{config}).then(()=>setMessage('工作流配置已保存；正在运行的任务保留原快照。')).catch(e=>setMessage(String(e)))}>保存工作流配置</button></>:null}
    {message?<p role="status">{message}</p>:null}
    <details><summary>内置执行模板（系统按任务选择，无需切换聊天模式）</summary>{templates.map(t=><p key={t.id}><strong>{t.name}</strong> · {t.applies_to}<br/>{t.failure_policy}</p>)}</details>
  </details>;
}
