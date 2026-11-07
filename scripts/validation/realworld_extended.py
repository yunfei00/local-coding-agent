"""Environment, continuity and delivery cases for the Phase 0 benchmark."""
from scripts.validation.realworld_cases import Case, py, PYTHON, FRONTEND, GIT

ENVIRONMENT = [
    Case("16","environment","依赖约束相容","修复 app 与 worker 的本地依赖声明冲突：app 兼容 >=2,<3，worker 必须继续要求 ==2.4.0。无需访问索引。",
         {"pyproject.toml":'[project]\nname="fixture-app"\nversion="0.1.0"\ndependencies=["shared>=3"]\n',
          "worker/pyproject.toml":'[project]\nname="fixture-worker"\nversion="0.1.0"\ndependencies=["shared==2.4.0"]\n'},
         """import tomllib
from pathlib import Path
from packaging.requirements import Requirement
read=lambda p: Requirement(tomllib.loads(Path(p).read_text())['project']['dependencies'][0])
a,b=read('pyproject.toml'),read('worker/pyproject.toml')
assert a.name==b.name=='shared' and '2.4.0' in a.specifier and '2.0' in a.specifier
assert '3.0' not in a.specifier and '1.9' not in a.specifier and str(b.specifier)=='==2.4.0'
""", preserve=("worker/pyproject.toml",)),
    Case("17","environment","uv 工作区成员路径","修复 uv 工作区成员引用到实际的 packages/mathlib。保持该包清单。使用 uv lock --offline 或等效本地检查验证。",
         {"pyproject.toml":'[project]\nname="uv-fixture"\nversion="0.1.0"\nrequires-python=">=3.12"\n[tool.uv.workspace]\nmembers=["packages/missing"]\n',
          "packages/mathlib/pyproject.toml":'[project]\nname="fixture-mathlib"\nversion="0.1.0"\nrequires-python=">=3.12"\n'},
         """import os,subprocess,tomllib
from pathlib import Path
assert tomllib.loads(Path('pyproject.toml').read_text())['tool']['uv']['workspace']['members']==['packages/mathlib']
p=subprocess.run(['uv','lock','--offline','--no-python-downloads'],timeout=20,capture_output=True)
assert p.returncode==0, 'uv offline resolution failed'
assert {p['name'] for p in tomllib.loads(Path('uv.lock').read_text())['package']}=={'fixture-mathlib','uv-fixture'}
""", preserve=("packages/mathlib/pyproject.toml",)),
    Case("18","environment","Node 本地依赖解析","修复 package.json 中本地 normalize 依赖路径，保留依赖包源码。可用 npm install --offline --ignore-scripts 验证。",
         {"package.json":'{"name":"fixture-app","version":"1.0.0","dependencies":{"normalize":"file:vendor/missing"}}',
          "vendor/normalize/package.json":'{"name":"normalize","version":"1.0.0","main":"index.cjs"}',
          "vendor/normalize/index.cjs":"module.exports = x => x.trim().toLowerCase();"},
         """import assert from 'node:assert/strict'; import fs from 'node:fs';
const p=JSON.parse(fs.readFileSync('package.json','utf8'));
const target=p.dependencies.normalize; assert.match(target,/^file:/);
const folder=target.slice(5); const manifest=JSON.parse(fs.readFileSync(folder+'/package.json','utf8'));
assert.equal(manifest.name,'normalize');
const normal=(await import('./'+folder+'/'+manifest.main)).default;
assert.equal(normal('  MiXeD  '),'mixed'); assert.equal(normal('  '),'');""",
         "node", preserve=("vendor/normalize/index.cjs","vendor/normalize/package.json")),
    py("19","environment","中文与空格路径","修复 UTF-8 文件读取：允许目录和文件名包含空格、中文；缺失文件仍抛 FileNotFoundError。",
       "from pathlib import Path\ndef operation(name): return Path(str(name).split()[0]).read_text(encoding='ascii')",
       """from pathlib import Path
d=Path('季度 文件'); d.mkdir(exist_ok=True); p=d/'报告 一.txt'; p.write_text('验证',encoding='utf-8')
assert handle(p)=='验证'
try: handle(d/'不存在.txt')
except FileNotFoundError: pass
else: raise AssertionError('missing path swallowed')
"""),
    py("20","environment","无 Git 工程版本","该目录不是 Git 仓库。让 handle(path) 读取传入路径（正常调用传 VERSION）并去掉行尾空白。传入文件缺失时返回 unknown。保持 VERSION 原样，不要初始化 Git。",
       "import subprocess\ndef operation(name): return subprocess.check_output(['git','describe'],text=True).strip()",
       """from pathlib import Path
assert not Path('.git').exists()
assert handle('VERSION')=='2.1.0'
assert handle('missing-version')=='unknown'
""",extra={"VERSION":"2.1.0\n"}, preserve=("VERSION",)),
]


def pipeline(id, category, title, task, *, control=""):
    domain="def operation(value): return value\n"
    return py(id,category,title,task,domain,
              """assert handle(['a=3','b=4','a=2','c=-1','bad','d=0'])=={'a':5,'b':4}
assert handle(['k=9','k=-10','z=bad'])=={}
assert handle([])=={}
""", extra={"parser.py":"def parse(line): return line.split('=',1)\n",
            "totals.py":"def total(rows): return dict(rows)\n",
            "test_contract.py":"import unittest\nfrom service import handle\nclass Contract(unittest.TestCase):\n def test_positive(self): self.assertEqual(handle(['a=1','a=2','b=-1','broken']),{'a':3})\n"},
              preserve=("test_contract.py",), control=control)


PIPELINE = "把多模块账本修复成输入 key=整数 的列表，忽略格式或数字无效的行，按 key 汇总，只返回总额大于零的项目。"
REPAIR = "请先运行 python -m unittest -q 复现失败，保持已有测试，修复后再次运行。"
LONG = [
    pipeline("21","long","分阶段账本","制定多阶段计划，先完善 parser.py，再完善 totals.py，最后连接 service 层并执行测试。"+PIPELINE),
    pipeline("22","long","失败驱动修复",REPAIR+PIPELINE),
    pipeline("23","long","断线恢复", "首先修复 parser.py，再完成汇总和接线。若中断请继续已完成工作。"+PIPELINE,control="resume"),
    pipeline("24","long","取消后重新执行", "按阶段执行，若取消后收到同一需求，检查当前文件再继续。"+PIPELINE,control="restart"),
    py("25","long","验证失败后修复","运行 python -m unittest -q，再修复订单定价；总价使用数量乘单价，会员总价打九折，数量或价格为负数时抛 ValueError。最后再次运行测试。",
       "def operation(value):\n count,price,member=value\n return price*.9 if member else price",
       """assert handle((3,100,True))==270
assert handle((0,100,False))==0
try: handle((-1,100,True))
except ValueError: pass
else: raise AssertionError('negative accepted')
""",extra={"test_order.py":"import unittest\nfrom service import handle\nclass Order(unittest.TestCase):\n def test_order(self): self.assertEqual(handle((2,50,False)),100)\n"},preserve=("test_order.py",)),
]

DELIVERY = [
    py("26","delivery","已有工程兼容修复","这是合成的已有日志工程。修复大小写不同的日志级别聚合，输出键统一小写。不改公开接口或已有文档。",
       "from collections import Counter\ndef operation(levels): return dict(Counter(levels))",
       "assert handle(['WARN','warn','info','Info','warn'])=={'warn':3,'info':2}\nassert handle([])=={}",
       extra={"README.md":"# 日志聚合器\nservice.handle(levels) 统计日志级别。\n"},preserve=("README.md",)),
    py("27","delivery","配额功能及测试","实现配额限制：handle((used, requested, limit)) 判断是否能申请，负数输入抛 ValueError。添加并运行 unittest 测试。",
       "def operation(values): return True",
       """from pathlib import Path
import subprocess, sys
assert handle((7,3,10)) and not handle((7,4,10))
try: handle((0,-1,10))
except ValueError: pass
else: raise AssertionError('negative accepted')
assert list(Path('.').glob('test_*.py'))
r=subprocess.run([sys.executable,'-m','unittest','discover'],capture_output=True,text=True,timeout=10)
assert r.returncode==0 and 'Ran 0 tests' not in r.stderr
"""),
    pipeline("28","delivery","多模块兼容重构",PIPELINE+"把解析和聚合分别保留在 parser.py 与 totals.py，domain.py 负责串联，保留公开接口。"),
    py("29","delivery","修复并提供可验证报告","修复 handle 的华氏到摄氏转换。提交 report.json，包含 checks 数组，每项具有 argv（字符串数组）和 exit_code，记录实际执行的 python -m unittest -q。",
       "def operation(f): return (f-32)*9/5",
       """import json,sys,subprocess
from pathlib import Path
assert handle(212)==100 and handle(-40)==-40
checks=json.loads(Path('report.json').read_text())['checks']
assert checks and all(c['argv']==['python','-m','unittest','-q'] for c in checks)
assert all(c['exit_code']==subprocess.run([sys.executable,*c['argv'][1:]],timeout=10).returncode==0 for c in checks)
""",extra={"test_temp.py":"import unittest\nfrom service import handle\nclass Temperature(unittest.TestCase):\n def test_f(self): self.assertEqual(handle(68),20)\n"},preserve=("test_temp.py",)),
    Case("30","delivery","完整库存 CLI","在现有空壳上实现库存 CLI inventory.py：add SKU COUNT、list。重复 add 累加；数量必须为正整数。用 inventory.json 持久化。list 输出 JSON 字典。提供 unittest 与运行说明。",
         {"inventory.py":"raise SystemExit('not implemented')\n","storage.py":"# Storage layer\n"},
         """import subprocess,sys,json
from pathlib import Path
def cli(*args): return subprocess.run([sys.executable,'inventory.py',*args],capture_output=True,text=True,timeout=8)
assert cli('add','X-17','3').returncode==0
assert cli('add','X-17','2').returncode==0
assert cli('add','X-17','-3').returncode!=0
r=cli('list')
assert r.returncode==0 and json.loads(r.stdout)=={'X-17':5}
assert json.loads(Path('inventory.json').read_text())=={'X-17':5}
assert Path('README.md').is_file() and list(Path('.').glob('test_*.py'))
r=subprocess.run([sys.executable,'-m','unittest','discover'],capture_output=True,text=True,timeout=10)
assert r.returncode==0 and 'Ran 0 tests' not in r.stderr
"""),
]

CASES = {c.id: c for c in (*PYTHON,*FRONTEND,*GIT,*ENVIRONMENT,*LONG,*DELIVERY)}
