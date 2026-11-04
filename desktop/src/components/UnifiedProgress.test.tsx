import {describe,it,expect,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {UnifiedProgress,type UnifiedRun} from './UnifiedProgress';
const base:UnifiedRun={id:'run',intent:'question',phase:'completed',outcome:'completed_verified',level:'none',changed_paths:[],verification:[]};
const actions={onResume:()=>{},onDiagnostics:()=>{}};
describe('统一 Agent 结果',()=>{
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
  it('诊断只按需加载，不自动展示历史',()=>{
    const onExport=vi.fn(async()=>({markdown:'历史不可默认展示',json_path:'history.json'}));
    const html=renderToStaticMarkup(<UnifiedProgress run={{...base,intent:'change'}} {...actions} onExport={onExport}/>);
    expect(onExport).not.toHaveBeenCalled();expect(html).toContain('查看当前诊断');expect(html).not.toContain('history.json');
  });
});
