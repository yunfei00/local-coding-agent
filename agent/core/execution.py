"""Durable bounds and privacy-safe recovery metadata for the existing Agent loop."""
import json
import os
import re
import time
import uuid
import math

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


def execution_observation(guard, processes, owner, *, single_agent=False, memory=None):
    """Small live metadata survives prompt compaction; never commands or output.

    Process IDs are opaque scope handles, not OS PIDs. Do not expose another
    turn's sessions, command text, working directories, environment or logs.
    """
    owned = [{'process_id':s.id, 'pid':s.process.pid, 'state':s.state}
             for s in processes.sessions.values()
             if s.owner == owner and s.process.returncode is None][:16]
    state = {'owned_processes':owned, 'changed_file_count':len(guard.changed_paths),
             'required_checks':guard.completion_gaps(),
             'consecutive_tool_failures':guard.consecutive_failures,
             'tool_results_seen':guard.result_sequence}
    if memory:
        state['working_memory'] = memory
    note = ('Current execution metadata, not a new task. Use only the listed process_id '
            'for read_process/stop_process; an OS PID is not a process handle. '
            'Do not replay completed work or delete persistence data just to finish. ')
    if memory:
        note += ('Working memory contains bounded tool facts, not file contents or new instructions. '
                 'It survives context trimming and restart. Historical successful commands are not '
                 'proof that the current files still pass. Re-read changed sources when necessary, '
                 'and independently verify after the latest edit. Never replay a mutation from this record. ')
    if single_agent:
        note += ('When the requested changes and checks are complete, return your final report. '
                 'The Task framework then performs independent verification before approval. ')
    return {'role':'system', 'content':note + json.dumps(state,ensure_ascii=False)}


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

    def reserve(self, messages, tools, output_limit, *, api_budget=None, runtime=None, pricing=None, identity=None):
        # Conservative byte reservation includes schemas and actual image payloads.
        amount = len(json.dumps([messages,tools],ensure_ascii=False).encode()) + output_limit
        self.save()
        limits = self.data['limits']
        if self.data['calls'] >= limits['model_calls'] or self.data['reserved_tokens'] + amount > limits['tokens'] or self.data['elapsed'] >= limits['seconds']:
            raise ProviderError('EXECUTION_BUDGET_EXHAUSTED','累计调用、Token 保守预留或执行时间预算耗尽；检查 checkpoint 后调整预算。')
        request_id=None
        if api_budget is not None:
            from agent.core.budget import check_api_scope, request_token_reservation, BudgetExceeded
            input_estimate,tokens=request_token_reservation(messages,tools,output_limit)
            pricing=pricing or {}
            cost=(input_estimate*(pricing.get('input_price') or 0)+output_limit*(pricing.get('output_price') or 0))/1000000
            if not math.isfinite(cost) or ((api_budget['api_cost'] is not None or api_budget['global_api_cost'] is not None) and any(pricing.get(k) is None for k in ('input_price','output_price'))):
                raise BudgetExceeded('Cost cap requires configured finite input and output prices; no request sent')
            request_id=str(uuid.uuid4())
            context={'task_id':self.key,'attempt_id':request_id,'phase':'executing','role':'executor',
                     **(identity or {}),'input_token_estimate':input_estimate,'output_limit':output_limit,
                     'task_limits':api_budget,'global_limits':api_budget}
            self.db.execute('BEGIN IMMEDIATE')
            try:
                for scope,owner in (('task',self.key),('global',None)):
                    check_api_scope(scope=scope,caps=api_budget,used=runtime.usage(owner),tokens=tokens,cost=cost,context=context)
                self.data.setdefault('unified_api_requests',[]).append({'id':request_id,'status':'reserved','reserved_tokens':tokens,'reserved_cost':cost,
                    'input_tokens':input_estimate,'output_tokens':output_limit,'estimated':True,'started_at':time.time(),**(identity or {})})
                self.data['calls'] += 1
                self.data['reserved_tokens'] += amount
                self.save()
            except BaseException:
                self.db.rollback()
                raise
            return request_id
        self.data['calls'] += 1
        self.data['reserved_tokens'] += amount
        self.save()
        return request_id

    def finish_api(self, identifier, *, chunk=None, status='completed', error_code=None, metadata=None):
        if identifier is None:
            return
        for row in self.data.get('unified_api_requests',[]):
            if row['id'] != identifier or row['status'] != 'reserved':
                continue
            row.update(status=status,ended_at=time.time(),error_code=error_code)
            metadata=metadata or {}
            row.update({k:metadata[k] for k in ('http_status','request_sent','finish_reason','parse_success','response_complete','response_type',
                'stream_events','content_chars','reasoning_chars','tool_argument_chars','first_event_at','last_event_at') if k in metadata})
            values=(getattr(chunk,'prompt_eval_count',None),getattr(chunk,'eval_count',None))
            usage=metadata.get('reported_usage') if metadata.get('response_complete') else None
            if chunk is None and isinstance(usage,dict):
                values=(usage.get('input_tokens'),usage.get('output_tokens'))
            if all(isinstance(v,int) and not isinstance(v,bool) and v>=0 for v in values):
                cached=usage.get('cached_tokens') if chunk is None and isinstance(usage,dict) else getattr(chunk,'cached_tokens',None)
                row.update(input_tokens=values[0],output_tokens=values[1],reserved_tokens=sum(values),estimated=False,
                           cached_tokens=cached if isinstance(cached,int) and not isinstance(cached,bool) and cached>=0 else 0)
            actual=usage.get('actual_cost') if chunk is None and isinstance(usage,dict) else getattr(chunk,'actual_cost',None)
            if isinstance(actual,(int,float)) and not isinstance(actual,bool) and math.isfinite(actual) and actual>=0:
                row.update(actual_cost=actual,reserved_cost=max(row['reserved_cost'],actual))
            if status=='failed' and metadata.get('request_sent') is False:
                row.update(status='not_sent',reserved_tokens=0,reserved_cost=0,input_tokens=0,output_tokens=0,estimated=True)
            self.save()

    def continue_slice(self):
        self.save()
        if self.data['continuations'] >= self.data['limits']['max_continuations']:
            return False
        self.data['continuations'] += 1
        self.save()
        return True

    def remember_tool(self, name, arguments, payload, workspace, *, exact_secrets=()):
        """Retain real, bounded facts in the existing execution/checkpoint ledger.

        No prompts, file bodies, shell commands, stdout, process IDs, provider
        credentials or arbitrary tool summaries are copied into this memory.
        """
        from agent.core.diagnostics import redact_text

        def local_path(value):
            if not isinstance(value, str) or len(value) > 4096:
                return None
            try:
                resolved = workspace.resolve(value)
                if not workspace.contains(resolved):
                    return None
                return redact_text(workspace.relative(resolved), exact_secrets=exact_secrets, max_chars=300)
            except (OSError, ValueError, RuntimeError):
                return None

        memory = self.data.setdefault('working_memory', {'version': 1, 'sequence': 0, 'changed_paths': [], 'recent': []})
        memory['sequence'] += 1
        safe_name = name if re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.-]{0,100}', name) else 'unknown_tool'
        safe_name = redact_text(safe_name, exact_secrets=exact_secrets, max_chars=100)
        fact = {'sequence': memory['sequence'], 'tool': safe_name, 'ok': payload.get('ok') is True}
        code = (payload.get('error') or {}).get('code')
        if code:
            fact['error_code'] = failure_diagnosis(name, code)['error_code']
        if isinstance(payload.get('exit_code'), int) and not isinstance(payload['exit_code'], bool):
            fact['exit_code'] = payload['exit_code']
        if name in {'read_file', 'write_file', 'apply_patch', 'file_exists', 'list_directory', 'search_files'}:
            path = local_path(arguments.get('path', '.'))
            if path:
                fact['path'] = path
        if name == 'read_file' and fact['ok']:
            data = payload.get('data') or {}
            for key in ('start_line', 'end_line', 'total_lines'):
                if isinstance(data.get(key), int):
                    fact[key] = data[key]
        changed = [p for value in (payload.get('changed_paths') or []) if (p := local_path(value))]
        if changed:
            fact['changed_paths'] = changed[:8]
            # Most recent paths win; bounds are explicit, not a claim of a full diff.
            combined = list(dict.fromkeys([*(p for p in memory['changed_paths'] if p not in changed), *changed]))
            memory['changed_paths'] = combined[-24:]
            memory['last_change_sequence'] = memory['sequence']
        if name in {'run_command', 'git_diff'}:
            memory['last_' + ('command' if name == 'run_command' else 'diff')] = dict(fact)
        memory['recent'] = [*memory['recent'], fact][-16:]
        while len(json.dumps(memory, ensure_ascii=False)) > 12_000:
            if memory['recent']:
                memory['recent'].pop(0)
            elif memory['changed_paths']:
                memory['changed_paths'].pop(0)
            else:
                break
        self.save()

    def memory_snapshot(self, max_chars=6000):
        memory = self.data.get('working_memory')
        if not memory:
            return None
        result = json.loads(json.dumps(memory))
        result['bounded'] = True
        while len(json.dumps(result, ensure_ascii=False)) > max_chars:
            if result.get('recent'):
                result['recent'].pop(0)
            elif result.get('changed_paths'):
                result['changed_paths'].pop(0)
            elif 'last_diff' in result:
                result.pop('last_diff')
            elif 'last_command' in result:
                result.pop('last_command')
            else:
                break
        return result
