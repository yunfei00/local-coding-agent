"""Synthetic, multi-module projects and private external scoring contracts."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    title: str
    prompt: str
    files: dict
    check: str
    language: str = "python"
    git: str = ""
    control: str = ""
    preserve: tuple = field(default_factory=tuple)

    def seed(self, work):
        for name, value in self.files.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        if self.git:
            git(work, "init", "-b", "main")
            git(work, "config", "--local", "user.email", "benchmark@example.invalid")
            git(work, "config", "--local", "user.name", "Benchmark")
            git(work, "config", "--local", "core.autocrlf", "false")
            git(work, "add", ".")
            git(work, "commit", "-qm", "fixture")
            if self.git == "conflict":
                git(work, "switch", "-qc", "incoming")
                (work / "feature.txt").write_text("incoming\n", encoding="utf-8")
                git(work, "commit", "-qam", "incoming")
                git(work, "switch", "-q", "main")
                (work / "feature.txt").write_text("main\n", encoding="utf-8")
                git(work, "commit", "-qam", "main")
                run(work, ["git", "merge", "incoming"], success=False)
                assert git(work, "ls-files", "-u"), "fixture_conflict_missing"
            if self.git == "restore":
                (work / "feature.txt").write_text("accidental edit\n", encoding="utf-8")
                git(work, "add", "feature.txt")

    def approve(self, tool, args):
        if tool in {"write_file", "apply_patch"}:
            return True  # The product workspace policy still resolves and checks paths.
        if tool == "git_commit":
            return self.git in {"commit", "conflict"}
        if tool != "run_command" or args.get("cwd") not in {None, "", "."}:
            return False
        command = args.get("command", "")
        ordinary = {"python -m unittest", "python -m unittest -q",
                    "python -m unittest discover", "npm test", "npm run build",
                    "uv lock --offline", "uv lock --offline --no-python-downloads",
                    "npm install --offline --ignore-scripts"}
        git_allowed = {
            "branch": {"git switch -c benchmark-fix", "git checkout -b benchmark-fix"},
            "commit": {'git commit -m "Enable feature"'},
            "conflict": {"git commit --no-edit"},
            "restore": {"git restore --source=HEAD --staged --worktree feature.txt",
                        "git restore --staged feature.txt", "git restore feature.txt"},
        }
        return command in ordinary or command in git_allowed.get(self.git, set())

    def score(self, work, evidence):
        for name in self.preserve:
            assert (work / name).read_text(encoding="utf-8") == self.files[name], "protected_fixture_changed"
        if self.git:
            if self.git == "branch":
                assert git(work, "branch", "--show-current") == "benchmark-fix", "wrong_branch"
            if self.git in {"commit", "conflict"}:
                assert not git(work, "status", "--porcelain"), "unclean_git_delivery"
                if self.git == "conflict":
                    assert len(git(work, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 3, "merge_commit_missing"
                else:
                    assert git(work, "rev-list", "--count", "HEAD") == "2", "expected_one_delivery_commit"
                    assert set(git(work, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) == {"feature.txt", "manual.txt"}, "commit_scope"
            if self.git == "diff":
                assert git(work, "diff", "--name-only") == "feature.txt", "diff_scope"
                assert not git(work, "diff", "--cached", "--name-only"), "unexpected_staging"
            if self.git == "restore":
                assert not git(work, "status", "--porcelain"), "staged_damage_not_restored"
            assert not git(work, "remote"), "unexpected_remote"
        if self.control:
            assert evidence.get("cancelled_generation") and evidence.get("reconnected"), "missing_cancel_or_reconnect"
            expected = "resume" if self.control == "resume" else "restart"
            assert evidence.get("control") == expected, "wrong_control_action"
        if self.id == "20":
            assert not (work / ".git").exists(), "unexpected_git_initialization"
        with tempfile.TemporaryDirectory(prefix="lca-score-") as temporary:
            copy = Path(temporary)
            snapshot(work, copy)
            if self.language == "node":
                run(copy, ["node", "--input-type=module", "-e", self.check])
            else:
                run(copy, [sys.executable, "-B", "-c", self.check])
        if self.id in {"10", "22", "25", "29"}:
            verify_command_evidence(self.id, evidence["tools"])


def verify_command_evidence(case_id, tools):
    succeeded = {t.get("verification_command") for t in tools if t["exit_code"] == 0}
    if case_id == "10":
        assert {"npm test", "npm run build"} <= succeeded, "npm_test_or_build_evidence_missing"
    elif case_id in {"22", "25", "29"}:
        assert "python -m unittest -q" in succeeded, "successful_unittest_evidence_missing"
        if case_id != "29":
            assert any(t.get("verification_command") == "python -m unittest -q" and t["exit_code"] == 1
                       for t in tools), "failing_unittest_evidence_missing"



def snapshot(source, target):
    """Copy only bounded project files; scoring must not mutate the delivery."""
    ignored = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    count = size = 0
    for directory, folders, files in os.walk(source, followlinks=False):
        folder = Path(directory)
        folders[:] = [name for name in folders if name not in ignored]
        for name in [*folders, *files]:
            path = folder / name
            assert not (path.is_symlink() or path.is_junction()), "snapshot_link_rejected"
        for name in files:
            path = folder / name
            assert path.is_file(), "snapshot_special_file"
            count += 1
            size += path.stat().st_size
            assert count <= 256 and size <= 16 * 1024 * 1024, "snapshot_budget_exceeded"
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


def run(work, command, *, success=True):
    environment = {key: os.environ[key] for key in (
        "PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"
    ) if key in os.environ}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, PYTHONUTF8="1")
    completed = subprocess.run(command, cwd=work, env=environment, capture_output=True, timeout=35,
                               encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    assert (completed.returncode == 0) == success, "external_command_exit_" + str(completed.returncode)
    return completed.stdout.strip()


def git(work, *args):
    return run(work, ["git", *args])


def py(id, category, title, task, domain, check, *, extra=None, **kwargs):
    files = {"domain.py": domain + "\n", "service.py": "from domain import operation\n\ndef handle(value):\n    return operation(value)\n"}
    files.update(extra or {})
    return Case(id, category, title, task + " 保留 service.handle(value) 公开接口。", files,
                "from service import handle\n" + check, **kwargs)


def js(id, title, task, impl, check, **extra):
    files = {"logic.mjs": impl + "\n", "page.mjs": "export { operation as handle } from './logic.mjs';\n",
             "package.json": '{"name":"realworld-fixture","version":"0.1.0","type":"module","scripts":{"test":"node --test","build":"node --check page.mjs"}}'}
    files.update(extra)
    return Case(id, "frontend", title, task + " 保留 page.mjs 的 handle 导出。", files,
                "import assert from 'node:assert/strict'; import {handle} from './page.mjs';\n" + check, "node")


PYTHON = [
    py("01", "python", "跨文件购物车金额", "修复购物车：每项价格乘数量，所有项加总，空车为零。",
       "def operation(items): return sum(price for price, quantity in items)",
       "assert handle([(3,4),(2,5)]) == 22\nassert handle([]) == 0"),
    py("02", "python", "折扣向后兼容", "在原整数输入保持原价的前提下，支持 (原价, 折扣百分比) 输入，返回折后金额。",
       "def operation(price): return price",
       "assert handle(170) == 170\nassert handle((350,20)) == 280\nassert handle((100,0)) == 100"),
    py("03", "python", "异常输入", "修复端口解析，拒绝布尔、非数字和超范围（1–65535）输入，统一抛 ValueError；接受数字字符串。",
       "def operation(value): return int(value)",
       "assert handle('1234') == 1234\nfor v in (True, 'x', 0, 65536):\n try: handle(v)\n except ValueError: pass\n else: raise AssertionError('invalid accepted')"),
    py("04", "python", "CLI 退出码", "完善 cli.py VALUE，输出合法端口整数。非法输入返回 2，并写 stderr。不要输出堆栈。",
       "def operation(value):\n port=int(value)\n if not 1 <= port <= 65535: raise ValueError('invalid port')\n return port",
       "import subprocess,sys\nfor value,code in [('3412',0),('0',2),('bad',2)]:\n r=subprocess.run([sys.executable,'cli.py',value],capture_output=True,text=True)\n assert r.returncode==code\n assert (r.stdout.strip()==value if code==0 else bool(r.stderr) and 'Traceback' not in r.stderr)",
       extra={"cli.py":"import sys\nfrom service import handle\nprint(handle(sys.argv[1]))\n"}),
    py("05", "python", "JSON 更新持久化", "修复持久化：handle((路径,键,值)) 写入 JSON，保留已有键，且已有 JSON 损坏时报告异常并保留原文件。",
       "import json\nfrom pathlib import Path\ndef operation(args):\n path,key,value=args\n Path(path).write_text(json.dumps({key:value}))",
       "from pathlib import Path\nimport json\np=Path('private-scoring-data.json')\np.write_text('{\"old\": 1}')\nhandle((p,'new',2))\nassert json.loads(p.read_text())=={'old':1,'new':2}\np.write_text('{bad')\ntry: handle((p,'next',3))\nexcept ValueError: pass\nelse: raise AssertionError('corruption swallowed')\nassert p.read_text()=='{bad'"),
]

FRONTEND = [
    js("06", "React 组件属性转换", "修复按钮组件的无障碍属性计算：忙碌或禁用均返回 disabled=true，保留其 label。",
       "export const operation = p => ({label:p.label,disabled:p.busy});",
       "assert.deepEqual(handle({label:'保存',disabled:true}),{label:'保存',disabled:true}); assert.equal(!!handle({busy:false}).disabled,false);",
       **{"Button.jsx":"import React from 'react'; import {handle} from './page.mjs'; export default function Button(p){const s=handle(p);return <button disabled={s.disabled}>{s.label}</button>;}"}),
    js("07", "不可变状态更新", "handle({state,id}) 返回删除指定 ID 后的列表，保留顺序，且不能修改原数组。",
       "export const operation=({state,id})=>{state.splice(state.findIndex(x=>x.id===id),1);return state;};",
       "const a=[{id:8},{id:3},{id:5}]; assert.deepEqual(handle({state:a,id:3}),[a[0],a[2]]); assert.equal(a.length,3); assert.deepEqual(handle({state:a,id:99}),a);"),
    js("08", "API 非成功状态", "handle(fetcher) 是异步接口；HTTP 非成功应 reject 且不得解析 JSON，成功返回 JSON。",
       "export const operation=async f=>(await f()).json();",
       "await assert.rejects(()=>handle(async()=>({ok:false,json(){assert.fail('parsed error body');}})),e=>e.code!=='ERR_ASSERTION'); assert.deepEqual(await handle(async()=>({ok:true,json:()=>({id:89})})),{id:89});"),
    js("09", "表单校验", "handle({email,amount}) 返回布尔值：邮箱简单校验需含 @ 与域名点，金额需为有限且大于零的数字。",
       "export const operation = v => Boolean(v.email && v.amount);",
       "assert.equal(handle({email:'a@b.test',amount:2}),true); for(const x of [{email:'abc',amount:2},{email:'a@b.test',amount:Infinity},{email:'a@b.test',amount:-2}]) assert.equal(handle(x),false);"),
    js("10", "构建与测试修复", "修复模块语法与单元测试失败，handle 将输入数组所有值相加，空数组为零。运行 npm test 和 npm run build。",
       "export const operation = values => values.reduce((a,b)=>a-b,0",
       "assert.equal(handle([9,-2,5]),12); assert.equal(handle([]),0);",
       **{"logic.test.mjs":"import assert from 'node:assert/strict';import {handle} from './page.mjs';assert.equal(handle([1,2]),3);"}),
]


GIT = [
    Case(id, "git", title, task + " 只使用本地 Git，不推送。", {"feature.txt":"base\n","manual.txt":"manual\n"},
         check, git=mode, preserve=() if mode == "commit" else ("manual.txt",))
    for id,title,mode,task,check in [
        ("11","创建工作分支","branch","创建并切换到 benchmark-fix 分支，保留现有文件，不要提交。",
         "from pathlib import Path\nassert Path('feature.txt').read_text()=='base\\n'"),
        ("12","多文件提交","commit","在 feature.txt 保留 base 并添加一行 enabled；manual.txt 保留 manual 并添加一行 enabled，做一次 git commit。",
         "from pathlib import Path\nfor f,v in [('feature.txt','base'),('manual.txt','manual')]: assert Path(f).read_text().splitlines()==[v,'enabled']"),
        ("13","合并冲突","conflict","解决已经发生的 merge 冲突，feature.txt 按 main、incoming 顺序各一行，完成 git commit。",
         "from pathlib import Path\nassert Path('feature.txt').read_text().splitlines()==['main','incoming']"),
        ("14","精确 Diff","diff","在 feature.txt 追加独立的一行 enabled，无额外空格。检查 diff，不暂存或提交。",
         "from pathlib import Path\nassert Path('feature.txt').read_text().splitlines()==['base','enabled']"),
        ("15","恢复错误暂存","restore","只将 feature.txt 的错误暂存和工作区改动恢复到 HEAD。保留 manual.txt，不要提交。",
         "from pathlib import Path\nassert Path('feature.txt').read_text().splitlines()==['base']"),
    ]
]
