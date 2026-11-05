"""有限只读检查与项目级修复方案；不修改全局 PATH、代理或缓存。"""
from pathlib import Path
import importlib.util
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from urllib.parse import urlsplit
from agent.core.diagnostics import redact_text
from agent.tools.base import ToolError,ToolResult

def classify_environment(code):
    text=str(code).lower()
    for needles,category in [(['dns','getaddrinfo'],'dns'),(['proxy'],'proxy'),(['timeout','timed_out'],'network_timeout'),(['connection','connect_failed'],'provider_connection'),(['permission','access_denied'],'permission'),(['module','dependency','import'],'dependency'),(['uv_','venv'],'python_environment'),(['git'],'git'),(['electron'],'electron')]:
        if any(n in text for n in needles):return category
    return 'configuration'

def probe_paths(manager):
    prefix=getattr(manager,'project_path_prefix',[])
    return os.pathsep.join([*prefix,os.environ.get('PATH','')])

class EnvironmentDiagnostics:
    def __init__(self,workspace,manager,knowledge=None):self.workspace,self.manager,self.knowledge=workspace,manager,knowledge

    async def check(self,component='all',module=None,*,owner='',on_output=None):
        if component not in {'all','git','npm','electron','python','uv','network','provider'}:raise ToolError('DIAGNOSTIC_COMPONENT_INVALID','未知诊断类型')
        if module and not re.fullmatch(r'[A-Za-z_]\w{0,100}',module):raise ToolError('INVALID_MODULE','依赖检查只接受单个 Python 模块名')
        root=self.workspace.root;checks=[];issues=[];path=probe_paths(self.manager)
        def add(code,reason,repair=None):issues.append({'code':code,'category':classify_environment(code),'reason':reason,'repair':repair})
        async def run(argv,label):
            try:
                result=await self.manager.run({'command':label,'timeout_seconds':20},owner=owner,argv=argv,on_output=on_output)
                checks.append({'command':label,'exit_code':result.exit_code,'summary':redact_text(result.stdout or result.stderr,max_chars=700),'log_path':result.data.get('log_path'),'duration_ms':result.duration_ms})
                return result
            except ToolError as exc:
                add(exc.code,'受管理检查未能完成：'+exc.code);return None
        if component in {'all','git'}:
            git=shutil.which('git',path=path)
            candidates=[Path(os.getenv('ProgramFiles','C:/Program Files'))/'Git/cmd/git.exe',Path('/usr/bin/git'),Path('/bin/git')]
            installed=next((str(p) for p in candidates if p.is_file()),None)
            if not git:add('GIT_PATH_INVALID' if installed else 'GIT_MISSING','Git 已安装但当前项目 PATH 未包含其目录' if installed else '当前 PATH 无 Git，标准安装位置也未发现；未自动安装软件',{'action':'project_git_path','directory':str(Path(installed).parent)} if installed else None)
            else:await run([git,'--version'],'git --version')
        if component in {'all','npm'}:
            if not shutil.which('npm',path=path):add('NPM_MISSING','当前 PATH 无 npm；需要受审批安装 Node.js')
        if component in {'all','npm','network'}:
            npmrc=root/'.npmrc'
            if npmrc.exists():
                if npmrc.is_symlink() or not self.workspace.contains(npmrc) or npmrc.stat().st_size>65536:add('NPM_PROXY_CONFIG_INVALID','项目 .npmrc 不在允许读取范围或过大')
                else:
                    for line in npmrc.read_text(encoding='utf-8').splitlines():
                        key,sep,value=line.partition('=')
                        if sep and key.strip().lower() in {'proxy','https-proxy'}:
                            try:
                                url=urlsplit(value.strip());port=url.port or (443 if url.scheme=='https' else 80)
                                if url.scheme not in {'http','https'} or not url.hostname:raise ValueError()
                                # Bounded TCP only, no credential-bearing HTTP requests.
                                import asyncio
                                reader,writer=await asyncio.wait_for(asyncio.open_connection(url.hostname,port),2)
                                writer.close();await writer.wait_closed()
                                checks.append({'command':'项目代理 TCP 连通性','exit_code':0,'summary':'代理端口可连接；不代表 npm 下载或认证成功'})
                            except (OSError,ValueError,TimeoutError):add('NPM_PROXY_UNREACHABLE','项目级代理无效或端口无法连接，未修改系统/用户代理',{'action':'project_npm_proxy_reset'})
        if component in {'all','electron'}:
            found=False
            for folder in [root/'node_modules/electron',root/'frontend/node_modules/electron']:
                if not folder.exists():continue
                found=True;file=folder/'path.txt'
                if not file.is_file():add('ELECTRON_CACHE_INVALID','Electron 包缺少 path.txt，下载/安装未完成；未删除缓存')
                else:
                    name=file.read_text(encoding='utf-8').strip();target=(folder/'dist'/name).resolve()
                    if not target.is_relative_to((folder/'dist').resolve()) or not target.is_file():add('ELECTRON_DOWNLOAD_INCOMPLETE','Electron 可执行文件缺失；未执行未知缓存内容')
                    else:
                        with target.open('rb') as handle:signature=handle.read(4)
                        if signature[:2]!=b'MZ' and signature!=b'\x7fELF' and signature not in {b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe'}:add('ELECTRON_CACHE_INVALID','Electron 二进制头损坏，未启动或删除缓存')
                        else:checks.append({'command':'Electron 包/二进制完整性','exit_code':0,'summary':'包声明的可执行文件及二进制头存在，未启动 Electron'})
            if not found:add('ELECTRON_NOT_INSTALLED','当前项目未安装 Electron；若不是桌面项目无需修复')
        if component in {'all','uv','python'}:
            uv=shutil.which('uv',path=path)
            if not uv:add('UV_MISSING','当前 PATH 没有 uv；未使用系统 pip 替代')
            configured=os.getenv('UV_PROJECT_ENVIRONMENT')
            if configured and Path(configured).resolve()!=(root/'.venv').resolve():add('UV_ENV_MISMATCH','UV_PROJECT_ENVIRONMENT 与本项目 .venv 不一致；未改全局环境')
            if module:
                python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
                if not python.exists():
                    add('PROJECT_VENV_MISSING','项目没有 .venv；下面仅检查 Agent 环境，不代表项目依赖已安装',{'action':'project_uv_sync','module':module})
                    python=Path(sys.executable)
                if getattr(sys,'frozen',False) and python==Path(sys.executable):add('PYTHON_CHECK_REQUIRES_VENV','打包 Agent 不能作为项目 Python；请先授权创建项目 uv 环境')
                else:
                    result=await run([str(python),'-c','import importlib.util,sys;sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 3)',module],'Python 依赖存在性检查：'+module)
                    if result and result.exit_code!=0:add('PYTHON_DEPENDENCY_MISSING','指定模块未安装于所检查解释器',{'action':'project_uv_sync','module':module})
        if component=='provider':
            if getattr(self,'provider_probe',None):
                result=await self.provider_probe();checks.extend(result['checks']);issues.extend(result['issues'])
            else:add('PROVIDER_CHECK_REQUIRED','请使用模型配置中的连接检测；凭据继续由现有安全存储处理，不从项目文件提取或写入诊断')
        return {'checks':checks,'issues':issues,'ok':not issues,'scope':'只读项目/环境检查，未修改系统全局配置','environment':{'platform':sys.platform,'agent_python':sys.version.split()[0]}}

    async def repair(self,action,*,directory=None,module=None,owner='',on_output=None):
        # Called only after the original permission engine grants this action.
        root=self.workspace.root
        if action not in {'project_npm_proxy_reset','project_git_path','project_uv_sync'}:raise ToolError('REPAIR_ACTION_INVALID','不支持该自动修复；未修改系统或缓存')
        before=await self.check('npm' if action=='project_npm_proxy_reset' else 'git' if action=='project_git_path' else 'python',module,owner=owner,on_output=on_output)
        if action=='project_npm_proxy_reset':
            file=root/'.npmrc'
            if file.is_symlink() or not self.workspace.contains(file) or not file.is_file() or file.stat().st_size>65536:raise ToolError('REPAIR_PATH_DENIED','只允许修改本项目普通 .npmrc 文件')
            text=file.read_text(encoding='utf-8');lines=[s for s in text.splitlines(keepends=True) if s.partition('=')[0].strip().lower() not in {'proxy','https-proxy'}]
            handle=tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=root,prefix='.lca-npmrc-',delete=False)
            try:
                with handle:handle.write(''.join(lines));handle.flush();os.fsync(handle.fileno())
                os.replace(handle.name,file)
            finally:
                if Path(handle.name).exists():Path(handle.name).unlink()
            verified=await self.check('npm',owner=owner,on_output=on_output)
            changed=['.npmrc']
        elif action=='project_git_path':
            path=Path(str(directory or '')).expanduser().resolve()
            binary=path/('git.exe' if os.name=='nt' else 'git')
            if not path.is_dir() or not binary.is_file():raise ToolError('GIT_PATH_INVALID','指定目录没有 Git；未修改 PATH')
            self.manager.project_path_prefix=[str(path)]
            verified=await self.check('git',owner=owner,on_output=on_output);changed=[]
            if self.knowledge and verified['ok']:self.knowledge.store.set_setting('project.path:'+self.knowledge.project_id,json.dumps([str(path)]))
        elif action=='project_uv_sync':
            uv=shutil.which('uv',path=probe_paths(self.manager))
            if not uv or not (root/'uv.lock').is_file() or not (root/'pyproject.toml').is_file():raise ToolError('UV_LOCK_REQUIRED','只允许已有锁文件的项目 uv sync；不安装全局软件')
            result=await self.manager.run({'command':'uv sync --locked --no-python-downloads','timeout_seconds':120},owner=owner,argv=[uv,'sync','--locked','--no-python-downloads'],on_output=on_output)
            if not result.ok:return result
            verified=await self.check('python',module,owner=owner,on_output=on_output);changed=[]
        else:raise ToolError('REPAIR_ACTION_INVALID','不支持该自动修复；未修改系统或缓存')
        if verified['ok'] and self.knowledge and self.knowledge.auto:
            self.knowledge.save('已验证环境修复：'+action,json.dumps({'action':action,'symptoms_and_cause':before['issues'],'checks':verified['checks'],'environment':verified['environment'],'scope':'仅本项目；历史验证结果，不代表当前环境永远正常'},ensure_ascii=False),'problem',trust='verified')
        return ToolResult(ok=verified['ok'],summary='修复后验证通过' if verified['ok'] else '修复已执行但重新验证未通过',data=verified,changed_paths=changed)
