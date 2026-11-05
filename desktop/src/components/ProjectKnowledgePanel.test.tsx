import {describe,it,expect,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {ProjectKnowledgePanel} from './ProjectKnowledgePanel';
import {ModelCapabilitySummary} from './ModelCapabilitySummary';

describe('项目知识与能力按需展开',()=>{
 it('默认渲染不会探测模型或加载全部项目历史',()=>{
  const taskRequest=vi.fn();vi.stubGlobal('window',{localAgent:{taskRequest}});
  const html=renderToStaticMarkup(<><ProjectKnowledgePanel threadId="thread" running={false}/><ModelCapabilitySummary/></>);
  expect(taskRequest).not.toHaveBeenCalled();expect(html).toContain('候选不是事实');expect(html).toContain('未知能力不会当作支持');expect(html).toContain('工程检索');vi.unstubAllGlobals();
 });
 it('运行时禁止修改记忆，但保留只读检索入口',()=>{
  const html=renderToStaticMarkup(<ProjectKnowledgePanel threadId="thread" running/>);
  expect(html).toMatch(/disabled=""[^>]*>保存并确认/);expect(html).toMatch(/<button type="button">搜索记忆/);
 });
});
