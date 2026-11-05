"""Transport-independent scheduling adapter for the original AgentServer loop."""
from __future__ import annotations

import asyncio
import json
import time


class BackgroundJobs:
    def __init__(self, db):
        self.db = db
        self.clients = set()
        self.condition = asyncio.Condition()
        self.running_claims = {}
        db.execute('CREATE TABLE IF NOT EXISTS agent_background_jobs (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, project_id TEXT NOT NULL, data_json TEXT NOT NULL)')
        for ident, raw in db.execute('SELECT id,data_json FROM agent_background_jobs').fetchall():
            data=json.loads(raw)
            if data['state'] in {'queued','running','waiting_approval'}:
                data.update(state='paused',reason='应用重启；请核对 Checkpoint 后恢复，未自动重放操作')
                db.execute('UPDATE agent_background_jobs SET data_json=? WHERE id=?',(json.dumps(data),ident))
        db.commit()

    def add(self, ident, thread_id, project_id):
        with self.db:
            self.db.execute('INSERT INTO agent_background_jobs VALUES(?,?,?,?)',
                (ident,thread_id,project_id,json.dumps({'state':'queued','revision':1,'created_at':time.time()})))

    def update(self, ident, state, reason=''):
        row=self.db.execute('SELECT data_json FROM agent_background_jobs WHERE id=?',(ident,)).fetchone()
        if not row:return
        data=json.loads(row[0])
        if data['state'] in {'completed','cancelled','failed'}:return
        data.update(state=state,reason=reason,revision=data['revision']+1,updated_at=time.time())
        with self.db:self.db.execute('UPDATE agent_background_jobs SET data_json=? WHERE id=?',(json.dumps(data),ident))

    def list(self, thread_id=None):
        return [{'id':i,'thread_id':t,'project_id':p,**json.loads(d)}
                for i,t,p,d in self.db.execute('SELECT id,thread_id,project_id,data_json FROM agent_background_jobs ORDER BY rowid DESC LIMIT 100')
                if thread_id is None or t==thread_id]

    async def send_json(self, event):
        ident=event.get('turn_id')
        kind=event.get('type')
        if kind=='agent.runtime.updated':
            runtime=event.get('payload',{}).get('runtime',{})
            phase=runtime.get('phase')
            if runtime.get('pending_approval') and phase not in {'paused','failed','cancelled','completed'}:
                self.update(ident,'waiting_approval')
            elif phase in {'planning','executing','verifying','repairing'}:
                self.update(ident,'running')
            elif phase in {'paused','failed','cancelled','completed'}:
                self.update(ident,'blocked' if phase=='completed' and runtime.get('outcome') in {'awaiting_user','partially_completed'} else phase,runtime.get('reason',''))
        elif kind=='approval.requested':self.update(ident,'waiting_approval')
        elif kind=='approval.resolved':self.update(ident,'running')
        elif kind in {'turn.cancelled','turn.failed'}:
            current=next((r for r in self.list() if r['id']==ident),{})
            if current.get('state') not in {'paused','blocked'}:
                self.update(ident,'cancelled' if kind=='turn.cancelled' else 'failed')
        for client in tuple(self.clients):
            try:
                if getattr(client,'closed',False):
                    self.clients.discard(client)
                    continue
                await asyncio.wait_for(client.send_json(event),timeout=2)
            except (ConnectionError,RuntimeError,asyncio.TimeoutError):
                self.clients.discard(client)

    async def run(self, ident, operation, *, claims=None, maximum=1):
        from agent.core.workflow import scheduling_conflict
        claims={**(claims or {}),'maximum':maximum}
        def available():
            if maximum>1 and self.running_claims:
                from agent.desktop.resources import require_resources,MIB
                try:require_resources(minimum_available=2560*MIB,minimum_commit=2560*MIB)
                except Exception:return False
            return (len(self.running_claims)<maximum and all(c['maximum']>len(self.running_claims) and not scheduling_conflict(claims,c) for c in self.running_claims.values()))
        try:
            async with self.condition:
                await self.condition.wait_for(available)
                self.running_claims[ident]=claims
            self.update(ident,'running')
            await operation()
        except asyncio.CancelledError:
            self.update(ident,'paused','任务中断；保留原执行账本和 Checkpoint')
            raise
        except Exception:
            self.update(ident,'failed','执行异常；检查原 Runtime 诊断')
            raise
        finally:
            async with self.condition:
                self.running_claims.pop(ident,None)
                self.condition.notify_all()
