"""Durable bounds and privacy-safe recovery metadata for the existing Agent loop."""
import json
import os
import re
import time

from agent.llm.base import ProviderError


def execution_policy():
    result = {}
    for name, default, minimum, maximum in (
        ('max_continuations', 2, 0, 8), ('model_calls', 512, 1, 512),
        ('tokens', 200000000, 1, 1000000000), ('seconds', 7200, 1, 86400)):
        value = int(os.getenv('LCA_EXECUTION_' + name.upper(), str(default)))
        if not minimum <= value <= maximum:
            raise ValueError('Invalid bounded execution policy: ' + name)
        result[name] = value
    return result


def failure_diagnosis(tool, code):
    """Fixed text only: provider/tool bodies can contain credentials or file text."""
    code = str(code or 'TOOL_FAILED')[:100]
    if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code):
        code = 'TOOL_FAILED'
    category, action, safe = 'tool', 'inspect_workspace', False
    if code in ('APPROVAL_DENIED','PERMISSION_DENIED') or 'SENSITIVE' in code or 'RISK_APPROVAL' in code:
        category, action = 'permission', 'request_explicit_approval'
    elif code.startswith('REPEATED_') or code == 'PLAN_OPERATION_ALREADY_APPLIED':
        category, action = 'repetition', 'inspect_existing_result'
    elif code in ('DESKTOP_WINDOW_SCOPE','DESKTOP_WINDOW_STALE','DESKTOP_WINDOW_NOT_FOUND'):
        category, action, safe = 'environment', 'rediscover_windows', True
    elif code in ('DESKTOP_SESSION_LOCKED','DESKTOP_SESSION_UNAVAILABLE','DESKTOP_FOCUS_FAILED'):
        category, action = 'environment', 'restore_interactive_session_then_rediscover'
    elif code in ('COMMAND_TIMEOUT','DESKTOP_TIMEOUT','DESKTOP_API_FAILED','SHELL_UNAVAILABLE'):
        category, action = 'environment', 'inspect_environment_and_timeout_before_retry'
    elif code.startswith('PROCESS_') or code in ('WORKING_DIRECTORY_UNAVAILABLE','FILE_NOT_FOUND','NOT_DIRECTORY'):
        category, action, safe = 'environment', 'inspect_workspace_and_processes', True
    elif code.startswith(('MODEL_','OPENAI_','OLLAMA_')):
        category, action = 'model', 'check_provider_and_budget'
    elif code in ('EXECUTION_BUDGET_EXHAUSTED','EXECUTION_TIMEOUT','MAX_MODEL_STEPS'):
        category, action = 'budget', 'review_checkpoint_and_explicitly_extend_budget'
    elif tool == 'run_command':
        category, action = 'test', 'inspect_test_failure_and_repair'
    elif code == 'DESKTOP_EDIT_REQUIRED':
        category, action = 'compatibility', 'inspect_edit_candidates_no_blind_input'
    return {'category':category, 'error_code':code, 'action':action, 'safe_probe':safe,
            'summary': {'permission':'需要明确授权或更换允许的操作。', 'repetition':'重复操作已拦截，请检查已有结果。',
                        'environment':'窗口、进程或工作目录可能失效，先重新发现环境。', 'model':'检查模型连接、响应及剩余预算。',
                        'test':'真实命令未通过，检查失败证据后修复。', 'compatibility':'当前控件不是标准 Edit；重新 inspect，禁止盲目输入。',
                        'budget':'累计执行边界已到，先检查 checkpoint；扩额需要明确确认。',
                        'tool':'工具失败，先检查当前工程和工具状态。'}[category]}


class ExecutionBudget:
    """Metadata ledger, not an execution loop. Task API BudgetGuard still applies."""
    def __init__(self, db, key, thread_id, policy):
        self.db, self.key = db, key
        db.execute('CREATE TABLE IF NOT EXISTS agent_execution_runs (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, data_json TEXT NOT NULL)')
        row = db.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(key,)).fetchone()
        self.data = json.loads(row[0]) if row else {'limits':dict(policy),'calls':0,'reserved_tokens':0,'continuations':0,'elapsed':0.0,'status':'running'}
        self.thread_id, self.started = thread_id, time.monotonic()
        self.data['status'] = 'running'
        self.save()

    def save(self):
        now = time.monotonic()
        self.data['elapsed'] += now - self.started
        self.started = now
        with self.db:
            self.db.execute('INSERT INTO agent_execution_runs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json',
                            (self.key,self.thread_id,json.dumps(self.data)))

    def bind_plan(self, plan_id):
        with self.db:
            self.db.execute('UPDATE agent_execution_runs SET id=? WHERE id=?',(plan_id,self.key))
        self.key = plan_id

    def reserve(self, messages, tools, output_limit):
        # Conservative byte reservation includes schemas and actual image payloads.
        amount = len(json.dumps([messages,tools],ensure_ascii=False).encode()) + output_limit
        self.save()
        limits = self.data['limits']
        if self.data['calls'] >= limits['model_calls'] or self.data['reserved_tokens'] + amount > limits['tokens'] or self.data['elapsed'] >= limits['seconds']:
            raise ProviderError('EXECUTION_BUDGET_EXHAUSTED','累计调用、Token 保守预留或执行时间预算耗尽；检查 checkpoint 后调整预算。')
        self.data['calls'] += 1
        self.data['reserved_tokens'] += amount
        self.save()

    def continue_slice(self):
        self.save()
        if self.data['continuations'] >= self.data['limits']['max_continuations']:
            return False
        self.data['continuations'] += 1
        self.save()
        return True
