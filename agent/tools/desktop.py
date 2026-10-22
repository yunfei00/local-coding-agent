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
    'desktop_screenshot': {'scope':{'type':'string','enum':['window','screen']}, 'share_with_model':{'type':'boolean','default':False}},
    'desktop_inspect': {}, 'desktop_focus_window': {},
    'desktop_click': {'x':{'type':'integer'},'y':{'type':'integer'}, 'method':{'type':'string','enum':['uia','coordinate']}},
    'desktop_type_text': {'text':{'type':'string','maxLength':4000}},
    'desktop_keypress': {'keys':{'type':'string','description':'Named key or chord e.g. CTRL+A, TAB, ENTER, CTRL+K (no arbitrary key script)'}},
    'desktop_scroll': {'direction':{'type':'string','enum':['up','down','left','right']},'amount':{'type':'integer','minimum':1,'maximum':10}},
    'desktop_wait': {'state':{'type':'string','enum':['exists','enabled','disabled','visible','hidden','name']},'expected':{'type':'string'},'seconds':{'type':'number','minimum':0,'maximum':30}},
}


class DesktopTool(BaseTool):
    def __init__(self, runtime, name):
        self.runtime, self.name = runtime, name
        self.description = name + ': current-session Windows UIA; explicit consent required. Inspect before input; never enter secrets.'
        keys = {'timeout_seconds'}
        if name != 'desktop_list_windows':
            keys.add('window_id')
        if name in ('desktop_click','desktop_type_text','desktop_keypress','desktop_scroll','desktop_wait'):
            keys.add('selector')
        if name in ('desktop_click','desktop_keypress','desktop_scroll'):
            keys.add('confirm_risk')
        required = [] if name == 'desktop_list_windows' else ['window_id']
        self.parameters = {'type':'object','properties':{**{k:v for k,v in PROPERTIES.items() if k in keys}, **EXTRA[name]}, 'required':required, 'additionalProperties':False}

    async def execute(self, arguments, *, on_output=None, owner_id='', desktop_authorized=False, supports_vision=False):
        return await self.runtime.execute(self.name, arguments, owner=owner_id, authorized=desktop_authorized, supports_vision=supports_vision)


def desktop_tools(runtime):
    return [DesktopTool(runtime, name) for name in NAMES]
