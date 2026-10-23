import {TaskSnapshot} from '../lib/autonomousTask';
import {ScreenshotPreview} from './ScreenshotPreview';

export function TaskEvidence({task}: {task:TaskSnapshot}) {
  const timeline=[...(task.transitions??[]).map((t,i)=>({id:'state'+i,at:t.at,text:`${t.from} → ${t.to}${t.error_code ? ' · '+t.error_code : ''}`})),
    ...(task.verification_history??[]).map((r,i)=>({id:'verify'+i,at:r.at,text:`Independent verification #${r.attempt}: ${r.passed ? 'PASS' : 'FAIL'}`}))].sort((a,b)=>a.at-b.at);
  const artifacts=new Map<string,{path:string;artifact_id:string}>();
  for(const test of [...(task.verification_history??[]).flatMap(r=>r.results),...task.verification])
    for(const e of test.evidence??[]) if(e.tool==='desktop_screenshot' && e.ok && e.path && e.artifact_id)
      artifacts.set(e.artifact_id,{path:e.path,artifact_id:e.artifact_id});
  return <>
    <details><summary>Task timeline · {timeline.length} events · {task.repairs} repairs</summary>
      <ol>{timeline.slice(-100).map(item=><li key={item.id}><time>{new Date(item.at*1000).toLocaleTimeString()}</time> · {item.text}</li>)}</ol>
    </details>
    {artifacts.size ? <details><summary>Screenshot artifacts · {artifacts.size}</summary><p>Local review only. Opening an artifact does not upload it to a model.</p>
      {[...artifacts.values()].map(item=><div key={item.artifact_id}><code>{item.artifact_id}</code><ScreenshotPreview path={item.path} /></div>)}
    </details> : null}
  </>;
}
