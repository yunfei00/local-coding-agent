import {describe,it,expect,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {UnifiedProgress,type UnifiedRun} from './UnifiedProgress';
const base:UnifiedRun={id:'run',intent:'question',phase:'completed',outcome:'completed_verified',level:'none',changed_paths:[],verification:[]};
const actions={onResume:()=>{},onDiagnostics:()=>{}};
describe('统一 Agent 结果',()=>{
  it('工作流进度来自真实步骤并显示角色和交付证据',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'complex',current_role:'tester',workflow_progress:{completed:2,total:4,percent:50,blocked:[]},role_handoffs:[{sequence:1,role:'reviewer',model:'actual-model',provider:'API',step_id:'s'}],plan:{steps:[{id:'s',description:'实际审查',state:'completed',workflow:{assigned_role:'reviewer',dependencies:['develop'],acceptance_criteria:['重新读取 Diff']}}]},delivery:{summary:'部分完成',md_path:'report.md',json_path:'report.json'}}} {...actions}/>);
    expect(html).toContain('2/4 (50%)');expect(html).toContain('actual-model');expect(html).toContain('重新读取 Diff');expect(html).toContain('report.json');
  });
  it('运行中提供暂停入口，已结束任务不提供暂停',()=>{
    const active=renderToStaticMarkup(<UnifiedProgress run={{...base,phase:'executing',outcome:undefined}} {...actions} onPause={()=>{}}/>);
    const ended=renderToStaticMarkup(<UnifiedProgress run={base} {...actions} onPause={()=>{}}/>);
    expect(active).toContain('暂停任务');expect(ended).not.toContain('暂停任务');
  });
  it('实际模型切换、压缩、记忆命中及恢复状态在同页可追踪',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,model:'actual-model',routing:{mode:'auto',reason:['能力匹配：工具调用'],switches:[{from:'a',to:'b',code:'MODEL_QUOTA_EXHAUSTED'}]},context_state:{compressed:true,recovered:true,memory_hits:2,retrieval_hits:3,index_version:4}}} {...actions}/>);
    expect(html).toContain('actual-model');expect(html).toContain('MODEL_QUOTA_EXHAUSTED');expect(html).toContain('上下文已压缩');expect(html).toContain('已恢复原执行状态');expect(html).toContain('记忆命中 2');
    expect(html).not.toContain('已完成 · 验证通过');
  });
  it('未知中断有明确的原计划审阅入口',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'change',phase:'failed',outcome:'failed',error_code:'PLAN_UNCERTAIN_EFFECTS'}} {...actions} onPlan={()=>{}}/>);
    expect(html).toContain('核对中断操作');expect(html).not.toContain('验证通过');
  });
  it('桌面动作没有独立合约时不声称验收通过',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'interaction',outcome:'completed_unverified',level:'manual'}} {...actions}/>);
    expect(html).toContain('桌面操作已结束 · 待独立验收');expect(html).not.toContain('验证通过');
  });
  it('没有持久化 Plan 的中断运行也有明确的原运行恢复入口',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'analysis',phase:'paused',outcome:'awaiting_user',reason:'后端中断'}} {...actions}/>);
    expect(html).toContain('检查并恢复原运行');expect(html).toContain('后端中断');
    expect(html).not.toContain('已完成 · 验证通过');
  });
  it('取消不显示成功，并保留显式恢复入口',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'change',phase:'cancelled',outcome:'cancelled'}} {...actions}/>);
    expect(html).toContain('已取消');expect(html).toContain('检查并恢复原运行');
    expect(html).not.toContain('已完成 · 验证通过');
  });
  it('问答不显示开发计划和测试面板',()=>{
    expect(renderToStaticMarkup(<UnifiedProgress run={base} {...actions}/>)).toBe('');
  });
  it('简单修改显示真实检查，不强制显示复杂计划',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'change',level:'targeted',changed_paths:['a.py'],verification:[{command:'uv run pytest',ok:true,exit_code:0,summary:'1 passed',log_path:'local.log'}]}} {...actions}/>);
    expect(html).toContain('已完成 · 验证通过');expect(html).not.toContain('持久化计划');
    expect(html).toContain('uv run pytest');expect(html).toContain('local.log');
  });
  it('环境失败不能显示验收通过，并提供同页恢复',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'change',phase:'paused',outcome:'awaiting_user',plan_id:'plan',reason:'missing dependency'}} {...actions}/>);
    expect(html).toContain('等待处理 · 验证受阻');expect(html).not.toContain('已完成 · 验证通过');expect(html).toContain('检查并继续未完成步骤');
  });
  it('复杂任务显示原持久化步骤状态',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'complex',plan:{steps:[{id:'s',description:'原步骤',state:'completed'}]}}} {...actions}/>);
    expect(html).toContain('原步骤');expect(html).toContain('completed');expect(html).toContain('持久化计划');
  });
  it('只读分析的失败命令是诊断证据，不显示验证通过',()=>{
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'analysis',diagnostic_checks:[{command:'uv run python -m unittest',exit_code:1,summary:'AssertionError'}]}} {...actions}/>);
    expect(html).toContain('只读诊断');expect(html).toContain('exit 1');expect(html).toContain('不代表测试通过');expect(html).not.toContain('已完成 · 验证通过');
  });
  it('诊断只按需加载，不自动展示历史',()=>{
    const onExport=vi.fn(async()=>({markdown:'历史不可默认展示',json_path:'history.json'}));
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'change'}} {...actions} onExport={onExport}/>);
    expect(onExport).not.toHaveBeenCalled();expect(html).toContain('查看当前诊断');expect(html).not.toContain('history.json');
  });
});
