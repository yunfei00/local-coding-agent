"""原执行账本的事件与消息元数据，不调度模型或执行工具。"""
from __future__ import annotations

import copy
from contextlib import nullcontext
import json
import re
import time
import uuid

from agent.core.diagnostics import redact_text


TRACE_FIELDS = frozenset({
    'step_id','from_step_id','sequence',
    'phase','previous_phase','generation','request_id','provider','model','role','route',
    'http_status','request_sent','network_attempted','error_code','category','recoverable',
    'retry','duration_ms','input_tokens','output_tokens','cached_tokens','estimated',
    'reserved_tokens','released_tokens','output_limit','context_window','message_id',
    'characters','boundary','reason','field','limit','used','required','scope',
    'stream_events','content_chars','reasoning_chars','tool_argument_chars',
    'first_event_at','last_event_at','response_complete','finish_reason','response_type',
    'attempt','recovery_limit','recovery_count','next_state','tool','exit_code','log_path',
    'status','settlement','reserved_cost','actual_cost',
})
ACTIVE_PHASES = {'queued','planning','executing','running','verifying','repairing','escalating','recovering'}
TERMINAL_PHASES = {'completed','failed','paused','cancelled'}
TRACE_LABELS={'request.prepared':'请求已准备','request.dispatched':'正在尝试连接/发送',
    'request.reserved':'请求预算已预留','request.settled':'请求预算已结算',
    'response.headers_received':'已收到 HTTP 响应头','response.streaming':'正在接收模型响应',
    'response.completed':'模型响应完成','request.failed':'请求失败','request.interrupted':'请求中断',
    'execution.transition':'执行状态变化','execution.interrupted':'后端中断已恢复为暂停',
    'followup.queued':'追加需求已排队','followup.applied':'追加需求已生效','task.transition':'Task 状态变化'}


def failure_class(code):
    code = str(code or "EXECUTION_FAILED")
    if code in {"MODEL_TRUNCATED", "MODEL_OUTPUT_LIMIT", "MODEL_TOOL_ARGUMENTS_TRUNCATED"}:
        return "OUTPUT_TRUNCATED"
    if "CONTEXT" in code:
        return "CONTEXT_LIMIT"
    if "TIMEOUT" in code:
        return "TIMEOUT"
    if code in {"CANCELLED", "USER_CANCELLED", "TURN_CANCELLED"}:
        return "USER_CANCELLED"
    if any(word in code for word in ("PERMISSION", "APPROVAL", "READ_ONLY")):
        return "TOOL_PERMISSION"
    if code.startswith(("DESKTOP_SESSION_", "BLOCKED_RESOURCE", "DESKTOP_FOCUS_", "ENVIRONMENT_")):
        return "ENVIRONMENT_FAILURE"
    if code.startswith(("OLLAMA_", "OPENAI_", "PROVIDER_")):
        return "PROVIDER_FAILURE"
    if code.startswith("MODEL_"):
        return "MODEL_FAILURE"
    if code.startswith("TOOL_") or code == "NON_ZERO_EXIT":
        return "TOOL_FAILURE"
    return "AGENT_FAILURE"


def failure_info(code):
    """固定中文说明，绝不把远端错误正文当作可公开诊断。"""
    code=str(code or 'EXECUTION_FAILED')
    if code=='REQUEST_CONSTRUCTION_FAILED':
        return {'category':'construction','recoverable':False,'reason':'请求构造或序列化失败；没有发出 HTTP 请求。'}
    if code=='REQUEST_TRACE_FAILED':
        return {'category':'environment','recoverable':False,'reason':'请求诊断无法写入本机存储，已停止执行。'}
    if code in {'MODEL_TIMEOUT','MODEL_REQUEST_TIMEOUT'} or 'NETWORK' in code or 'STREAM_FAILED' in code:
        return {'category':'network','recoverable':True,'reason':'模型连接中断或单次请求超时；已保留请求状态与预算，请在连接恢复后继续。'}
    if 'AUTH' in code or 'PERMISSION' in code or 'APPROVAL' in code:
        return {'category':'permission','recoverable':False,'reason':'连接权限或操作审批未满足；没有绕过权限执行。'}
    if 'BUDGET' in code:
        return {'category':'budget','recoverable':False,'reason':'预算预检阻止请求；请查看具体上限、累计值和本次所需预留。'}
    if 'CANCEL' in code:
        return {'category':'cancelled','recoverable':False,'reason':'用户已取消本次尝试；不会自动重新运行。'}
    if code in {'BACKEND_INTERRUPTED','CONNECTION_INTERRUPTED','MODEL_INTERRUPTED'}:
        return {'category':'interrupted','recoverable':True,'reason':'执行连接或后端中断；已保留检查点，恢复前核对工作区。'}
    if code.startswith(('MODEL_','OPENAI_','OLLAMA_','PLAN_JSON','PLAN_SCHEMA')):
        return {'category':'model','recoverable':False,'reason':'模型响应或协议不符合要求；已停止本次尝试，未执行无效工具参数。'}
    if 'VERIFICATION' in code:
        return {'category':'verification','recoverable':False,'reason':'独立验证未通过或环境受阻；查看命令、退出码和原始日志。'}
    return {'category':'tool','recoverable':False,'reason':'执行未完成；保留具体错误码与执行证据供检查。'}


class RuntimeLedger:
    def __init__(self, db, secrets=lambda: ()):
        self.db,self.secrets=db,secrets
        db.executescript('''
            CREATE TABLE IF NOT EXISTS runtime_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                kind TEXT NOT NULL, event_key TEXT NOT NULL, request_id TEXT,
                created_at REAL NOT NULL, metadata_json TEXT NOT NULL,
                UNIQUE(run_id,event_key)
            );
            CREATE INDEX IF NOT EXISTS runtime_event_thread ON runtime_events(thread_id,sequence);
            CREATE TABLE IF NOT EXISTS runtime_followups (
                run_id TEXT NOT NULL, thread_id TEXT NOT NULL, message_id TEXT NOT NULL,
                text TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL,
                PRIMARY KEY(run_id,message_id)
            );
        ''')
        db.commit()

    def clean(self, metadata):
        result={}
        for key,value in metadata.items():
            if key not in TRACE_FIELDS:continue
            if isinstance(value,str):
                value=redact_text(value,exact_secrets=tuple(self.secrets()),max_chars=1000)
                value=re.sub(r'(?im)(\bcookie\s*[:=])[^\r\n]*',r'\1<REDACTED>',value)
            elif value is not None and not isinstance(value,(int,float,bool)):continue
            result[key]=value
        if result.get('error_code'):
            result['failure_class'] = failure_class(result['error_code'])
        return result

    def record(self, run_id, thread_id, kind, metadata=None, *, request_id=None, event_key=None, commit=True):
        if not re.fullmatch(r'[a-z_.]{1,80}',kind):raise ValueError('事件类型不合法')
        identifier=uuid.uuid4().hex
        with self.db if commit else nullcontext():
            self.db.execute('INSERT OR IGNORE INTO runtime_events(event_id,run_id,thread_id,kind,event_key,request_id,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,?)',
                (identifier,run_id,thread_id,kind,event_key or identifier,request_id,time.time(),json.dumps(self.clean(metadata or {}),ensure_ascii=False,allow_nan=False)))
        row=self.db.execute('SELECT * FROM runtime_events WHERE run_id=? AND event_key=?',(run_id,event_key or identifier)).fetchone()
        return self._event(row)

    @staticmethod
    def _event(row):
        return {'sequence':row[0],'event_id':row[1],'run_id':row[2],'thread_id':row[3],
                'kind':row[4],'label':TRACE_LABELS.get(row[4],row[4]),'request_id':row[6],'at':row[7],'metadata':json.loads(row[8])}

    def events(self, *, run_id=None, thread_id=None, after=0, limit=100):
        limit=max(1,min(500,int(limit)))
        field,value=('run_id',run_id) if run_id is not None else ('thread_id',thread_id)
        rows=self.db.execute(f'SELECT * FROM runtime_events WHERE {field}=? AND sequence>? ORDER BY sequence DESC LIMIT ?',
                             (value,int(after),limit)).fetchall()
        return [self._event(r) for r in reversed(rows)]

    def request_callback(self, run_id, thread_id, request_id, identity):
        def observe(stage, metadata):
            owner=run_id() if callable(run_id) else run_id
            details={**identity,**metadata}
            if details.get('error_code'):
                details.update(failure_info(details['error_code']))
            return self.record(owner,thread_id,stage,details,request_id=request_id,event_key=request_id+':'+stage)
        return observe

    def rebind(self, old, new, *, commit=True):
        with self.db if commit else nullcontext():
            self.db.execute('UPDATE runtime_events SET run_id=? WHERE run_id=?',(new,old))
            self.db.execute('UPDATE runtime_followups SET run_id=? WHERE run_id=?',(new,old))

    def enqueue(self, run_id, thread_id, message_id, text, *, persist=None):
        if not isinstance(text,str) or not 1<=len(text.strip())<=4000:raise ValueError('追加需求须为 1～4000 字符')
        if not isinstance(message_id,str) or not re.fullmatch(r'[\w.:-]{1,128}',message_id):raise ValueError('追加消息 ID 不合法')
        text=text.strip()
        existing=self.db.execute('SELECT text FROM runtime_followups WHERE run_id=? AND message_id=?',(run_id,message_id)).fetchone()
        if existing:
            if existing[0]!=text:raise ValueError('相同追加消息 ID 的内容不能改变')
            return False
        count,total=self.db.execute('SELECT count(*),coalesce(sum(length(text)),0) FROM runtime_followups WHERE run_id=?',(run_id,)).fetchone()
        if count>=32 or total+len(text)>32000:raise ValueError('本次运行的追加需求已达到数量或长度上限')
        with self.db:
            self.db.execute('INSERT INTO runtime_followups(run_id,thread_id,message_id,text,created_at) VALUES(?,?,?,?,?)',(run_id,thread_id,message_id,text,time.time()))
            if persist:persist(text)
            self.record(run_id,thread_id,'followup.queued',{'message_id':message_id,'characters':len(text),'boundary':'下一次模型请求前'},event_key='queued:'+message_id,commit=False)
        return True

    def pending(self, run_id):
        return [{'message_id':r[0],'text':r[1]} for r in self.db.execute("SELECT message_id,text FROM runtime_followups WHERE run_id=? AND state='pending' ORDER BY rowid",(run_id,))]

    def apply_followups(self, execution, apply):
        rows=self.pending(execution.key)
        if not rows:return []
        before=copy.deepcopy(execution.data)
        runtime=execution.data.get('unified')
        try:
            with self.db:
                apply(rows)
                execution.save(commit=False)
                for row in rows:
                    self.db.execute("UPDATE runtime_followups SET state='applied' WHERE run_id=? AND message_id=?",(execution.key,row['message_id']))
                    self.record(execution.key,execution.thread_id,'followup.applied',{'message_id':row['message_id'],'boundary':'完整工具批次之后、模型请求之前'},event_key='applied:'+row['message_id'],commit=False)
        except BaseException:
            execution.data.clear();execution.data.update(before)
            if runtime is not None:
                runtime.clear();runtime.update(before.get('unified',{}));execution.data['unified']=runtime
            raise
        return rows

    def transition(self, execution, phase, generation, **values):
        if phase not in ACTIVE_PHASES | TERMINAL_PHASES:
            raise ValueError('未知执行阶段：'+str(phase))
        runtime=execution.data['unified']
        stored=self.db.execute('SELECT data_json FROM agent_execution_runs WHERE id=?',(execution.key,)).fetchone()
        latest=json.loads(stored[0]).get('unified',{}) if stored else runtime
        if latest.get('generation')!=generation:return None
        if latest.get('cancelled_generation')==generation and phase!='cancelled':
            runtime.update(latest)
            return None
        previous=latest.get('phase')
        # 恢复由入口显式核对工作区并建立新 generation。旧尝试的终态
        # 不能被迟到的验证/网络回调重新打开或改写成其他终态。
        if previous in TERMINAL_PHASES and phase!=previous:
            runtime.update(latest)
            return None
        runtime.update(values,phase=phase)
        if phase=='cancelled':runtime['cancelled_generation']=generation
        with self.db:
            event=self.record(execution.key,execution.thread_id,'execution.transition',{'previous_phase':previous,'phase':phase,'generation':generation,'error_code':runtime.get('error_code')},commit=False)
            runtime['event_id']=event['event_id']
            execution.save(commit=False)
        return event

    def export_run(self, path, run_id=None, *, thread_id=None):
        """完整事件留本机文件，不把所有历史塞进 WebSocket。"""
        count=0
        with path.open('w',encoding='utf-8') as file:
            file.write('[')
            field,value=('run_id',run_id) if run_id is not None else ('thread_id',thread_id)
            for row in self.db.execute(f'SELECT * FROM runtime_events WHERE {field}=? ORDER BY sequence',(value,)):
                if count:file.write(',\n')
                file.write(json.dumps(self._event(row),ensure_ascii=False));count+=1
            file.write(']\n')
        return count

    def recover_executions(self):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_execution_runs'").fetchone():return 0
        count=0
        for row in self.db.execute('SELECT id,thread_id,data_json FROM agent_execution_runs').fetchall():
            data=json.loads(row[2]);runtime=data.get('unified')
            if not runtime or runtime.get('phase') not in ACTIVE_PHASES:continue
            if runtime.pop('pending_approval',None):runtime['approval_reconfirmation_required']=True
            runtime.update(phase='paused',outcome='awaiting_user',error_code='BACKEND_INTERRUPTED',reason=failure_info('BACKEND_INTERRUPTED')['reason'],revision=runtime.get('revision',0)+1,updated_at=time.time())
            data.update(status='paused',last_error='BACKEND_INTERRUPTED')
            for request in data.get('unified_api_requests',[]):
                if request['status']=='reserved':request.update(status='interrupted',error_code='MODEL_INTERRUPTED',ended_at=time.time())
            with self.db:
                self.db.execute('UPDATE agent_execution_runs SET data_json=? WHERE id=?',(json.dumps(data,ensure_ascii=False),row[0]))
                self.record(row[0],row[1],'execution.interrupted',{'phase':'paused','error_code':'BACKEND_INTERRUPTED','generation':runtime.get('generation')},commit=False)
            count+=1
        return count
