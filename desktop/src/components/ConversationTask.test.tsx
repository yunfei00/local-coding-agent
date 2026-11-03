import {describe,it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {ConversationTask} from './ConversationTask';
import {TaskSnapshot} from '../lib/autonomousTask';
describe('in-conversation development',()=>{
  it('shows real phase, evidence, model and review controls without a second goal form',()=>{
    const task={id:'task',status:'awaiting_approval',reason:'Verified',workspace:'worktree',usage:{api_calls:2,reserved_tokens:300},
      calls:[{role:'executor',model:'configured-model'}],plan:{steps:[{id:'step',description:'Implement',state:'completed'}]},verification:[],
      report:{review:'交付报告',diff:'+ actual change'}} as unknown as TaskSnapshot;
    const html=renderToStaticMarkup(<ConversationTask task={task} onAction={()=>{}} onDetails={()=>{}}/>);
    expect(html).toContain('configured-model');expect(html).toContain('接受已验证结果');
    expect(html).toContain('completed');expect(html).not.toContain('<textarea');
  });
});
