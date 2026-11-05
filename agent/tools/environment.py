from agent.tools.base import BaseTool,ToolResult

class EnvironmentDiagnoseTool(BaseTool):
    name='environment_diagnose'
    description='执行有限的只读环境检查：Git/PATH、npm 项目代理连通性、Electron 包/缓存、Python 模块、uv 环境。返回真实命令退出码、根因分类和受审批修复建议；不会安装软件、修改系统代理或删除缓存。'
    parameters={'type':'object','properties':{'component':{'type':'string','enum':['all','git','npm','electron','python','uv','network','provider']},'module':{'type':'string'}},'additionalProperties':False}
    def __init__(self,diagnostics):self.diagnostics=diagnostics
    async def execute(self,arguments,*,owner_id='',on_output=None):
        data=await self.diagnostics.check(arguments.get('component','all'),arguments.get('module'),owner=owner_id,on_output=on_output)
        return ToolResult(ok=True,summary='只读诊断完成；'+str(len(data['issues']))+' 项问题（不是验证通过声明）',data=data)

class EnvironmentRepairTool(BaseTool):
    name='environment_repair'
    description='必须经现有审批的项目级环境修复：移除项目 .npmrc 代理、给本项目子进程添加 Git PATH、执行已有 uv.lock 的 uv sync。随后实际重新诊断并记录验证结果；不改系统/用户全局配置，不删除缓存。'
    parameters={'type':'object','properties':{'action':{'type':'string','enum':['project_npm_proxy_reset','project_git_path','project_uv_sync']},'directory':{'type':'string'},'module':{'type':'string'}},'required':['action'],'additionalProperties':False}
    def __init__(self,diagnostics):self.diagnostics=diagnostics
    async def execute(self,arguments,*,owner_id='',on_output=None):return await self.diagnostics.repair(arguments['action'],directory=arguments.get('directory'),module=arguments.get('module'),owner=owner_id,on_output=on_output)
