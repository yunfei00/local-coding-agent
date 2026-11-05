import asyncio
import sqlite3
import unittest
from unittest.mock import patch

from agent.core.background import BackgroundJobs
from agent.tools.base import ToolError


class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.jobs=BackgroundJobs(self.db)

    async def test_parallel_disjoint_workspaces_and_release(self):
        entered=asyncio.Event();release=asyncio.Event();count=0;peak=0
        async def operation():
            nonlocal count,peak
            count+=1;peak=max(count,peak)
            if count==2:entered.set()
            await release.wait();count-=1
        with patch('agent.desktop.resources.require_resources',return_value={}):
            tasks=[asyncio.create_task(self.jobs.run(str(i),operation,claims={'workspace':str(i)},maximum=2)) for i in range(2)]
            await asyncio.wait_for(entered.wait(),1)
            release.set();await asyncio.gather(*tasks)
        self.assertEqual(peak,2);self.assertEqual(self.jobs.running_claims,{})

    async def test_same_worktree_gui_and_low_memory_serialize(self):
        for claims,low_memory in [([{'workspace':'a'},{'workspace':'a'}],False),
                                  ([{'workspace':'a','gui':True},{'workspace':'b','gui':True}],False),
                                  ([{'workspace':'a'},{'workspace':'b'}],True)]:
            with self.subTest(claims=claims,low_memory=low_memory):
                started=asyncio.Event();release=asyncio.Event();second=asyncio.Event()
                async def first():started.set();await release.wait()
                async def after():second.set()
                with patch('agent.desktop.resources.require_resources',side_effect=ToolError('BLOCKED_RESOURCE','low') if low_memory else None):
                    one=asyncio.create_task(self.jobs.run('1',first,claims=claims[0],maximum=2));await started.wait()
                    two=asyncio.create_task(self.jobs.run('2',after,claims=claims[1],maximum=2))
                    await asyncio.sleep(.01);self.assertFalse(second.is_set())
                    release.set();await asyncio.wait_for(asyncio.gather(one,two),1)
                self.assertTrue(second.is_set())

    async def test_cancel_waiting_job_never_executes_it(self):
        started=asyncio.Event();release=asyncio.Event();executed=[]
        async def first():started.set();await release.wait()
        async def second():executed.append('unsafe')
        self.jobs.add('2','t','p')
        one=asyncio.create_task(self.jobs.run('1',first,claims={'workspace':'a'}));await started.wait()
        two=asyncio.create_task(self.jobs.run('2',second,claims={'workspace':'b'}));await asyncio.sleep(0)
        self.jobs.update('2','cancelled');two.cancel()
        await asyncio.gather(two,return_exceptions=True);release.set();await one
        self.assertEqual(executed,[]);self.assertEqual(self.jobs.list()[0]['state'],'cancelled')

    async def test_transport_loss_does_not_throw_into_runtime(self):
        class LostClient:
            closed=False
            async def send_json(self,event):raise ConnectionResetError('closed')
        client=LostClient();self.jobs.clients.add(client)
        self.jobs.add('job','t','p')
        await self.jobs.send_json({'type':'turn.failed','turn_id':'job','payload':{}})
        await self.jobs.send_json({'type':'agent.runtime.updated','turn_id':'job','payload':{'runtime':{'phase':'completed'}}})
        self.assertEqual(self.jobs.clients,set());self.assertEqual(self.jobs.list()[0]['state'],'failed')


if __name__=='__main__':unittest.main()
