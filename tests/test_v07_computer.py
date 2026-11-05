import asyncio
import copy
import unittest
import tempfile
from unittest.mock import AsyncMock,patch
from agent.desktop.resources import require_resources,MIB
from agent.desktop.visual_target import resolve_visual_point,coordinate_grid
from agent.desktop.runtime import DesktopRuntime
from agent.tools.base import ToolError
from types import SimpleNamespace
from agent.desktop.worker import document_reader,DesktopError,controls
from agent.core.unified_runtime import computer_only

class ComputerContracts(unittest.IsolatedAsyncioTestCase):
    def test_gui_fixture_preflight_blocks_before_any_desktop_probe(self):
        import windows_desktop_support as support
        with patch('windows_desktop_support.require_resources',side_effect=ToolError('BLOCKED_RESOURCE','low memory')),patch('windows_desktop_support.require_interactive_session') as session,patch.dict('os.environ',{'LCA_REQUIRE_INTERACTIVE_DESKTOP':'0'}):
            with self.assertRaises(unittest.SkipTest) as e:support.require_test_desktop()
            self.assertIn('BLOCKED_RESOURCE',str(e.exception));session.assert_not_called()
    def test_coordinate_grid_does_not_modify_original_capture(self):
        from PIL import Image
        original=Image.new('RGB',(768,543),(23,105,220));before=original.tobytes()
        annotated=coordinate_grid(original)
        self.assertEqual(original.tobytes(),before);self.assertEqual(annotated.size,original.size);self.assertNotEqual(annotated.tobytes(),before)
    def test_explicit_computer_scope_does_not_restrict_code_tasks(self):
        self.assertTrue(computer_only('在桌面窗口点击按钮，禁止读取 HTML 源码，只操作界面。'))
        self.assertFalse(computer_only('修复 src/App.tsx 并在界面点击按钮验证。'))
    def test_modern_deep_tree_is_readable_but_bounds_still_fail_closed(self):
        class Node:
            def __init__(self,n,children=()):self.element_info=SimpleNamespace(runtime_id=[n]);self.nodes=children
            def children(self):return self.nodes
        root=Node(15)
        for n in range(14,-1,-1):root=Node(n,[root])
        items,truncated,_=controls(root);self.assertEqual(len(items),16);self.assertFalse(truncated)
        for n in range(16,30):root=Node(n,[root])
        self.assertTrue(controls(root)[1])
        items,truncated,_=controls(Node(999,[Node(n) for n in range(300)]))
        self.assertEqual(len(items),200);self.assertTrue(truncated)
    def test_document_editor_requires_pattern_and_rejects_web_document(self):
        control=SimpleNamespace(element_info=SimpleNamespace(control_type='Document',class_name='Chrome_RenderWidgetHostHWND'))
        with self.assertRaises(DesktopError):document_reader(control)
        control.element_info.class_name='RichEditD2DPT'
        control.iface_text=SimpleNamespace(DocumentRange=SimpleNamespace(GetAttributeValue=lambda _:False,GetText=lambda _:'中文\r\n第二行\r'))
        self.assertEqual(document_reader(control)(),'中文\n第二行')
        control.iface_text.DocumentRange.GetAttributeValue=lambda _:True
        with self.assertRaises(DesktopError):document_reader(control)
    def receipt(self):return {'owner':'task','window_id':'window','scope':'window','shared':True,'captured_at':100,'client_size':[1200,800],'client_origin':[40,60],'dpi':144,'model_image_size':[600,400],'image_size':[1200,800]}
    def resolve(self,receipt=None,**arguments):
        r=self.receipt() if receipt is None else receipt
        return resolve_visual_point({'x':300,'y':200,**arguments},r,owner='task',window_id='window',geometry=self.receipt(),now=110)
    def test_scaled_image_maps_to_physical_client(self):self.assertEqual(self.resolve(),(601,401))
    def test_explicit_normalized_space_has_no_pixel_ambiguity(self):
        self.assertEqual(self.resolve(x=500,y=500,coordinate_space='normalized_1000'),(600,400))
        self.assertEqual(self.resolve(x=1000,y=1000,coordinate_space='normalized_1000'),(1199,799))
    def test_foreign_capture_or_window_cannot_authorize(self):
        for field in ['owner','window_id']:
            r=self.receipt();r[field]='other'
            with self.assertRaises(ToolError) as e:self.resolve(r)
            self.assertEqual(e.exception.code,'DESKTOP_CAPTURE_SCOPE')
    def test_only_explicitly_shared_window_image_is_accepted(self):
        for changes in [{'shared':False},{'scope':'screen'}]:
            r={**self.receipt(),**changes}
            with self.assertRaises(ToolError) as e:self.resolve(r)
            self.assertEqual(e.exception.code,'DESKTOP_IMAGE_NOT_SHARED')
    def test_stale_dpi_move_and_resize_require_new_capture(self):
        for change in [{'captured_at':-100},{'dpi':96},{'client_origin':[0,0]},{'client_size':[200,200]}]:
            with self.assertRaises(ToolError) as e:self.resolve({**self.receipt(),**change})
            self.assertEqual(e.exception.code,'DESKTOP_CAPTURE_STALE')
    def test_invalid_points_are_not_coerced(self):
        for value in [True,-1,600,1.5,'3']:
            with self.assertRaises(ToolError):self.resolve(x=value)
    def test_low_physical_or_commit_memory_blocks_without_spawning(self):
        for a,c in [(1,2048),(2048,1)]:
            with self.assertRaises(ToolError) as e:require_resources({'supported':True,'available_bytes':a*MIB,'commit_available_bytes':c*MIB})
            self.assertEqual(e.exception.code,'BLOCKED_RESOURCE')
    async def test_low_resource_prevents_worker_process_creation(self):
        runtime=DesktopRuntime()
        with patch('agent.desktop.runtime.sys.platform','win32'),patch('agent.desktop.resources.memory_snapshot',return_value={'supported':True,'available_bytes':1,'commit_available_bytes':1}),patch('asyncio.create_subprocess_exec',new_callable=AsyncMock) as spawn:
            with self.assertRaises(ToolError) as e:await runtime._worker({},1)
            self.assertEqual(e.exception.code,'BLOCKED_RESOURCE');spawn.assert_not_awaited()
    async def test_mapping_uses_existing_scoped_authorized_worker(self):
        runtime=DesktopRuntime();r=self.receipt();r['captured_at']=__import__('time').time()
        runtime.windows['window']={'owner':'task','native':{},'geometry':{k:r[k] for k in ('client_size','dpi','client_origin')}}
        runtime.artifacts['capture']=r;runtime._worker=AsyncMock(return_value={'clicked':True})
        await runtime.execute('desktop_click',{'window_id':'window','method':'coordinate','coordinate_space':'model_image','artifact_id':'capture','x':300,'y':200,'confirm_risk':True},owner='task',authorized=True)
        request=runtime._worker.await_args.args[0];self.assertEqual((request['arguments']['x'],request['arguments']['y']),(601,401))
        with self.assertRaises(ToolError):await runtime.execute('desktop_click',{},owner='other',authorized=False)
    async def test_identical_recapture_retains_mapping_and_new_grid_is_not_deduplicated(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'LCA_DATA_DIR':folder}):
            runtime=DesktopRuntime();runtime.windows['w']={'owner':'t','native':{'pid':1,'generation':'unit'}}
            async def worker(request,timeout):
                Image.new('RGB',(1200,800),(23,105,220)).save(request['artifact_path'])
                return {'client_size':[1200,800],'client_origin':[0,0],'dpi':96,'width':1200,'height':800,'redacted_controls':0}
            runtime._worker=worker
            args={'window_id':'w','share_with_model':True}
            first=await runtime.execute('desktop_screenshot',args,owner='t',authorized=True,supports_vision=True)
            runtime.image_message('t',consume=True)
            second=await runtime.execute('desktop_screenshot',args,owner='t',authorized=True,supports_vision=True)
            self.assertEqual(second.data['vision_feedback'],'unchanged_capture_not_attached')
            self.assertEqual(second.data['model_image_size'],[768,512]);self.assertTrue(runtime.artifacts[second.data['artifact_id']]['shared'])
            third=await runtime.execute('desktop_screenshot',{**args,'coordinate_grid':True},owner='t',authorized=True,supports_vision=True)
            self.assertEqual(third.data['vision_feedback'],'image_attached');self.assertEqual(first.data['sha256'],third.data['sha256'])
            await runtime.close_owner('t');self.assertEqual(runtime.artifacts,{})

class ComputerLoopScope(unittest.IsolatedAsyncioTestCase):
    async def test_forged_file_tool_cannot_escape_gui_only_scope(self):
        import test_unified_runtime as fixtures
        from test_agent_reliability import FakeWebSocket,ScriptedProvider,tool_step
        fixture=fixtures.UnifiedLoopTests('runTest');await fixture.asyncSetUp()
        try:
            fixture.server._authorize_tool=AsyncMock(return_value={'ok':True,'changed_paths':[]})
            ws=FakeWebSocket();provider=ScriptedProvider([tool_step('write_file',{'path':'forged.py','content':'bad'})])
            await fixture.server.run_tool_turn(ws,thread_id=fixture.thread.id,turn_id='v07-scope',prompt='在桌面窗口点击按钮，只操作界面，禁止读取 HTML 源码。',model='mock',provider=provider,unified=True)
            self.assertTrue(any(e['payload'].get('code')=='COMPUTER_TOOL_SCOPE' for e in ws.messages))
            fixture.server._authorize_tool.assert_not_awaited();self.assertFalse((fixture.repo/'forged.py').exists())
        finally:await fixture.asyncTearDown()
