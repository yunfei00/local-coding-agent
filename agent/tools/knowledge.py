from agent.tools.base import BaseTool,ToolResult,ToolError
import sqlite3

class KnowledgeSearchTool(BaseTool):
    name='knowledge_search'
    description='检索当前项目真实代码、文档、配置。返回路径、准确行号、片段、原因与索引版本；无 Embedding；读取前重新核实项目权限、忽略规则与敏感信息。'
    parameters={'type':'object','properties':{'query':{'type':'string','maxLength':500},'mode':{'type':'string','enum':['all','filename','content','symbol']},'limit':{'type':'integer','minimum':1,'maximum':20}},'required':['query'],'additionalProperties':False}
    def __init__(self,knowledge):self.knowledge=knowledge
    async def execute(self,arguments,*,on_output=None):
        try:result=self.knowledge.search(arguments['query'],arguments.get('mode','all'),arguments.get('limit',8))
        except ValueError as exc:raise ToolError('KNOWLEDGE_QUERY_INVALID',str(exc)) from exc
        except sqlite3.Error as exc:raise ToolError('KNOWLEDGE_STORAGE_UNAVAILABLE','知识索引存储暂不可用；原记忆未删除。') from exc
        return ToolResult(ok=True,summary=f"找到 {len(result['results'])} 项真实工程证据",data=result)

class ProjectMemoryTool(BaseTool):
    name='project_memory'
    description='读取或保存当前项目的重要知识（禁止凭据和聊天原文）。模型保存内容始终为未验证候选，不得声称已验证；用户可在项目上下文中确认、编辑、删除。代码事实以当前文件为准。'
    parameters={'type':'object','properties':{'action':{'type':'string','enum':['search','save']},'query':{'type':'string','maxLength':500},'title':{'type':'string','maxLength':160},'content':{'type':'string','maxLength':6000},'category':{'type':'string','enum':['project','convention','architecture','problem','decision']},'sources':{'type':'array','items':{'type':'string'},'maxItems':12}},'required':['action'],'additionalProperties':False}
    def __init__(self,knowledge):self.knowledge=knowledge
    async def execute(self,arguments,*,on_output=None,owner_id=''):
        try:return self._execute(arguments,owner_id=owner_id)
        except ValueError as exc:raise ToolError('PROJECT_MEMORY_REJECTED',str(exc)) from exc
        except sqlite3.Error as exc:raise ToolError('KNOWLEDGE_STORAGE_UNAVAILABLE','记忆存储暂不可用；原记忆未删除。') from exc
    def _execute(self,arguments,owner_id=''):
        if arguments['action']=='save':
            if not self.knowledge.auto and owner_id not in getattr(self.knowledge,'explicit_save_owners',set()):raise ToolError('MEMORY_AUTOSAVE_DISABLED','自动记忆已关闭，且本轮用户未明确要求保存；未写入候选。')
            explicit=getattr(self.knowledge,'explicit_rules',{}).get(owner_id,[])
            user_rule=str(arguments.get('content','')).strip() in explicit
            item=self.knowledge.save(arguments.get('title',''),arguments.get('content',''),'convention' if user_rule else arguments.get('category','decision'),trust='user' if user_rule else 'candidate',sources=arguments.get('sources',[]))
            return ToolResult(ok=True,summary='已保存用户明确约定' if user_rule else '已保存候选记忆，尚未验证',data={'memory':item})
        return ToolResult(ok=True,summary='当前项目记忆',data={'memories':self.knowledge.list(arguments.get('query',''))})

class ProjectMemorySearchTool(ProjectMemoryTool):
    name='project_memory_search'
    description='只读检索当前项目长期记忆，保留候选/用户规则/已验证事实与来源状态，不能修改或跨项目读取。'
    parameters={'type':'object','properties':{'query':{'type':'string','maxLength':500}},'additionalProperties':False}
    async def execute(self,arguments,*,on_output=None):return self._execute({'action':'search','query':arguments.get('query','')})
