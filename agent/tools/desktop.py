from agent.desktop.runtime import NAMES
from agent.tools.base import BaseTool

PROPERTIES = {
    'window_id': {'type':'string', 'description':'Opaque window_id from desktop_list_windows in this task'},
    'timeout_seconds': {'type':'number', 'minimum':0.1, 'maximum':60},
    'selector': {'type':'object', 'description':'Exact UIA selector. Prefer automation_id/control_type/name or runtime_id returned by inspect. Ambiguous matches fail.',
                 'properties':{'automation_id':{'type':'string'}, 'name':{'type':'string'}, 'control_type':{'type':'string'}, 'runtime_id':{'type':'array','items':{'type':'integer'}}}, 'additionalProperties':False},
    'confirm_risk': {'type':'boolean', 'description':'Request fresh human approval for a high-risk or unclassified target'},
}
EXTRA = {
    'desktop_list_windows': {'pid':{'type':'integer','minimum':1}},
    'desktop_screenshot': {'scope':{'type':'string','enum':['window','screen']}, 'share_with_model':{'type':'boolean','default':False},'coordinate_grid':{'type':'boolean','default':False,'description':'仅在已授权发送的模型缩略图上标注0..1000坐标网格，原截图不改；辅助视觉定位。'}},
    'desktop_inspect': {}, 'desktop_focus_window': {},
    'desktop_click': {'x':{'type':'integer'},'y':{'type':'integer'}, 'method':{'type':'string','enum':['uia','coordinate']},
                      'coordinate_space':{'type':'string','enum':['client','model_image','normalized_1000'],'description':'model_image 为本次缩放图片的像素；normalized_1000 为0..1000归一化坐标。视觉回退必须提供 artifact_id 并再次批准，不能混用空间。'},'artifact_id':{'type':'string'}},
    'desktop_type_text': {'text':{'type':'string','maxLength':4000,'description':'Exact requested replacement text; do not add quotes, whitespace or key names.'}},
    'desktop_keypress': {'keys':{'type':'string','description':'Named key or chord e.g. CTRL+A, TAB, ENTER, CTRL+S (no arbitrary key script). Saving with CTRL+S requires confirm_risk and fresh approval.'}},
    'desktop_scroll': {'direction':{'type':'string','enum':['up','down','left','right']},'amount':{'type':'integer','minimum':1,'maximum':10}},
    'desktop_wait': {'state':{'type':'string','enum':['exists','enabled','disabled','visible','hidden','name']},'expected':{'type':'string','description':'state=name时必须与desktop_inspect观测的完整控件名称精确相等；不支持正则、前缀或包含匹配。状态名变化时用稳定automation_id定位。'},'seconds':{'type':'number','minimum':0,'maximum':30}},
}


class DesktopTool(BaseTool):
    def __init__(self, runtime, name):
        self.runtime, self.name = runtime, name
        self.description = name + ': current-session Windows UIA; explicit consent required. Inspect before input; never enter secrets.'
        if name == 'desktop_click':
            self.description += ' Exact editable selectors focus the editor via UIA; buttons use InvokePattern.'
        keys = {'timeout_seconds'}
        if name != 'desktop_list_windows':
            keys.add('window_id')
        if name in ('desktop_click','desktop_type_text','desktop_keypress','desktop_scroll','desktop_wait'):
            keys.add('selector')
        if name in ('desktop_click','desktop_keypress','desktop_scroll','desktop_type_text'):
            keys.add('confirm_risk')
        required = [] if name == 'desktop_list_windows' else ['window_id']
        if name == 'desktop_type_text':
            required.extend(('selector', 'text'))
            self.description += ' Reuse the exact editable selector from inspection even if the editor is already focused.'
        elif name == 'desktop_keypress':
            required.append('keys')
        self.parameters = {'type':'object','properties':{**{k:v for k,v in PROPERTIES.items() if k in keys}, **EXTRA[name]}, 'required':required, 'additionalProperties':False}

    async def execute(self, arguments, *, on_output=None, owner_id='', desktop_authorized=False, supports_vision=False):
        return await self.runtime.execute(self.name, arguments, owner=owner_id, authorized=desktop_authorized, supports_vision=supports_vision)


def desktop_tools(runtime):
    return [DesktopTool(runtime, name) for name in NAMES]
