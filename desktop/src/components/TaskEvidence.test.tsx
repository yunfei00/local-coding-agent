import {it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {TaskEvidence} from './TaskEvidence';
import {TaskSnapshot} from '../lib/autonomousTask';

it('retains failed rounds and local artifacts when a later verification passes',()=>{
  const result={command:'GUI acceptance',ok:false,summary:'Actual assertion failed',evidence:[{tool:'desktop_screenshot',ok:true,path:'local.png',artifact_id:'capture_fixture'}]};
  const task={repairs:1,transitions:[{at:1,from:'executing',to:'verifying'}],verification:[{...result,ok:true}],
    verification_history:[{at:2,attempt:1,passed:false,results:[result]},{at:3,attempt:2,passed:true,results:[]}]} as TaskSnapshot;
  const html=renderToStaticMarkup(<TaskEvidence task={task} />);
  expect(html).toContain('#1: FAIL');expect(html).toContain('#2: PASS');
  expect(html).toContain('1 repairs');expect(html).toContain('Screenshot artifacts · 1');
  expect(html).toContain('View local screenshot');expect(html).not.toContain('data:image');
});
