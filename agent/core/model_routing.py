"""扩展原 Catalog 的能力证据和规则选择；调用仍走现有 Runtime/预算。"""
import json
import hashlib
import re
import time
from agent.llm.base import ProviderError

SUPPORTED,UNSUPPORTED,UNKNOWN='SUPPORTED','UNSUPPORTED','UNKNOWN'
CAPS=('chat','streaming','tools','vision','structured')
CAP_NAMES={'chat':'对话','streaming':'流式响应','tools':'工具调用','vision':'视觉理解','structured':'结构化输出'}

def prohibited(model):
    normalized=re.sub(r'[^a-z0-9]','',str(model).lower())
    return any(name in normalized for name in ('qwen38flash','qwen37plus'))

def require_allowed(model):
    if prohibited(model):raise ProviderError('MODEL_PROHIBITED','该模型已被用户禁止，未发送请求。',recoverable=False)

def requirements(prompt):
    from agent.core.unified_runtime import requested_intent
    request=requested_intent(prompt);caps={'chat'};tags=[request['kind']]
    if request['kind']!='question':caps.add('tools')
    if re.search(r'截图|视觉|图片|图像|screenshot|\bimage\b',prompt,re.I) or request['kind']=='interaction':caps.update({'vision','tools'});tags.append('视觉理解')
    if re.search(r'JSON|结构化|schema',prompt,re.I):caps.add('structured');tags.append('结构化输出')
    minimum=max(4096,len(prompt.encode())//2+2048)
    if minimum>12000:tags.append('长上下文')
    if re.search(r'推理|证明|reason',prompt,re.I):tags.append('复杂推理')
    if re.search(r'开发|新增|创建|实现|generate',prompt,re.I):tags.append('代码生成')
    if re.search(r'修复|修改|重构|fix|refactor',prompt,re.I):tags.append('代码修改')
    return {'capabilities':sorted(caps),'context_minimum':minimum,'tags':tags}

class CapabilityRegistry:
    def __init__(self,catalog):self.catalog=catalog;self.store=catalog.store
    def key(self,pid):return 'model.capability.v1:'+pid
    def history(self,pid,fingerprint):
        try:data=json.loads(self.store.get_setting(self.key(pid)) or '{}')
        except (ValueError,TypeError):return {}
        if not isinstance(data,dict) or data.get('fingerprint')!=fingerprint:return {}
        for field in ('detected_at','unavailable_until','successes','failures','latency_ms'):
            value=data.get(field)
            if field in data and not (field=='latency_ms' and value is None) and (isinstance(value,bool) or not isinstance(value,(int,float)) or not __import__('math').isfinite(value) or value<0):return {}
        caps=data.get('capabilities',{})
        if not isinstance(caps,dict):return {}
        data['capabilities']={key:value for key,value in caps.items() if key in CAPS and isinstance(value,dict) and value.get('state') in {SUPPORTED,UNSUPPORTED,UNKNOWN} and isinstance(value.get('detected_at'),(int,float))}
        return data
    def availability_key(self,profile):
        connection=next(c for c in self.catalog.load()['connections'] if c['connection_id']==profile['connection_id'])
        identity=[profile['connection_id'],profile['model_id'],connection['base_url'],connection['provider_type'],connection['credential_reference']]
        return 'model.availability.v1:'+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    def state(self,profile):
        pid=profile['model_profile_id'];fingerprint=self.catalog.fingerprint(pid)
        history=self.history(pid,fingerprint)
        result={cap:{'state':UNKNOWN,'source':'未知'} for cap in CAPS}
        # Actual evidence outranks declared configuration; stale evidence is ignored.
        if profile.get('supports_vision') is True:result['vision']={'state':SUPPORTED,'source':'用户明确配置'}
        if profile.get('tool_mode')=='native':result['tools']={'state':SUPPORTED,'source':'用户明确配置'}
        tested=self.catalog.test_result(pid)
        from datetime import datetime,timezone
        try:
            probe_time=datetime.fromisoformat(tested['tested_at'].replace('Z','+00:00')).timestamp()
            age=time.time()-probe_time
        except (ValueError,TypeError,KeyError):age=10**9;probe_time=0
        if tested.get('live') and tested.get('configuration')!='STALE' and -5<=age<=30*86400:
            for cap,field in [('chat','text'),('vision','vision'),('tools','tools')]:
                value=tested.get(field)
                if value in {'PASS','FAIL'}:result[cap]={'state':SUPPORTED if value=='PASS' else UNSUPPORTED,'source':'真实能力探针','detected_at':tested.get('tested_at')}
            if tested.get('tools')=='PASS':result['structured']={'state':SUPPORTED,'source':'已校验 JSON 工具参数'}
        if 0<=time.time()-history.get('detected_at',0)<=30*86400:
            for cap,evidence in history.get('capabilities',{}).items():
                if cap in CAPS and isinstance(evidence,dict) and 0<=time.time()-evidence.get('detected_at',0)<=30*86400 and (result[cap].get('source') not in {'真实能力探针','已校验 JSON 工具参数'} or evidence['detected_at']>=probe_time):result[cap]=evidence
        actual_unavailable=self.store.get_setting(self.availability_key(profile))=='quota_exhausted'
        blocked=history.get('unavailable_until',0)>time.time() or actual_unavailable
        return {'model_profile_id':pid,'model_id':profile['model_id'],'connection_id':profile['connection_id'],'display_name':profile['display_name'],
            'capabilities':result,'context_window':profile.get('context_window'),'max_output_tokens':profile.get('max_output_tokens'),
            'availability':'UNAVAILABLE' if blocked or prohibited(profile['model_id']) else 'AVAILABLE' if result['chat']['state']==SUPPORTED else UNKNOWN,
            'successes':history.get('successes',0),'failures':history.get('failures',0),'latency_ms':history.get('latency_ms'),
            'last_success':history.get('last_success'),'last_failure':history.get('last_failure'),'detected_at':history.get('detected_at'),
            'prohibited':prohibited(profile['model_id'])}

    def record(self,pid,*,success=False,tools=False,streaming=False,error=None,latency_ms=None,expected_fingerprint=None):
        try:profile=next(p for p in self.catalog.load()['profiles'] if p['model_profile_id']==pid);fingerprint=self.catalog.fingerprint(pid)
        except (StopIteration,ValueError):return
        if expected_fingerprint is not None and expected_fingerprint!=fingerprint:return
        data=self.history(pid,fingerprint)
        now=time.time();data.update(fingerprint=fingerprint,detected_at=now)
        if success:
            self.store.set_setting(self.availability_key(profile),'')
            data['successes']=data.get('successes',0)+1;data['last_success']=now;data['quota_exhausted']=False;data['unavailable_until']=0
            caps=data.setdefault('capabilities',{});caps['chat']={'state':SUPPORTED,'source':'真实模型调用','detected_at':now}
            for cap,value in [('tools',tools),('structured',tools),('streaming',streaming)]:
                if value:caps[cap]={'state':SUPPORTED,'source':'真实模型响应','detected_at':now}
        else:
            data['failures']=data.get('failures',0)+1;data['last_failure']={'at':now,'code':str(error)}
            if error=='MODEL_QUOTA_EXHAUSTED':
                data['quota_exhausted']=True
                self.store.set_setting(self.availability_key(profile),'quota_exhausted')
            if error in {'MODEL_NOT_FOUND','MODEL_TOOLS_UNAVAILABLE','MODEL_VISION_UNAVAILABLE'}:
                data['unavailable_until']=now+3600
            if error in {'MODEL_TOOLS_UNAVAILABLE','MODEL_VISION_UNAVAILABLE'}:
                data.setdefault('capabilities',{})['tools' if error=='MODEL_TOOLS_UNAVAILABLE' else 'vision']={'state':UNSUPPORTED,'source':'真实能力错误','detected_at':now}
        if latency_ms is not None:data['latency_ms']=max(0,min(600000,latency_ms))
        self.store.set_setting(self.key(pid),json.dumps(data))

    def candidates(self,need):
        catalog=self.catalog.load();enabled={c['connection_id'] for c in catalog['connections'] if c['enabled']};rows=[]
        for p in catalog['profiles']:
            if p['connection_id'] not in enabled or prohibited(p['model_id']):continue
            s=self.state(p)
            if s['availability']=='UNAVAILABLE' or any(s['capabilities'][c]['state']!=SUPPORTED for c in need['capabilities']):continue
            window=p.get('context_window')
            if not window or window-(p.get('max_output_tokens') or 1024)<need['context_minimum']:continue
            total=s['successes']+s['failures'];score=100+(10*s['successes']/total if total else 0)-min((s['latency_ms'] or 0)/10000,10)
            reason=['能力匹配：'+','.join(CAP_NAMES[c] for c in need['capabilities']),f'配置上下文 {window}，输出预留 {p.get("max_output_tokens") or 1024}',f'真实成功/失败 {s["successes"]}/{s["failures"]}']
            rows.append({'profile_id':p['model_profile_id'],'score':score,'reason':reason,'snapshot':{'profile':self.catalog.profile(p['model_profile_id']),'capabilities':self.catalog.test_result(p['model_profile_id']),'request_seconds':120,'fingerprint':self.catalog.fingerprint(p['model_profile_id'])}})
        selected=[];seen=set()
        for row in sorted(rows,key=lambda x:(-x['score'],x['profile_id'])):
            p=row['snapshot']['profile'];identity=(p['_connection']['connection_id'],p['model'])
            if identity not in seen:selected.append(row);seen.add(identity)
        return selected

    def prepare(self,selection,prompt,*,allow_fallback=False):
        need=requirements(prompt);mode='auto' if selection=='auto' else 'manual';rows=self.candidates(need)
        from agent.llm.router import validate_config
        timeout=validate_config(json.loads(self.store.get_setting('orchestration.config') or '{}'))['budget']['request_seconds']
        for row in rows:row['snapshot']['request_seconds']=timeout
        if mode=='auto':
            if not rows:raise ProviderError('MODEL_NO_CAPABLE_CANDIDATE','当前配置没有能力已确认且可用的候选模型。请在模型配置中执行能力检测；未知能力不会视为支持。')
            chosen=rows[0]
        else:
            pid=selection.removeprefix('profile:');profile=next(p for p in self.catalog.load()['profiles'] if p['model_profile_id']==pid);require_allowed(profile['model_id']);state=self.state(profile)
            unsupported=[c for c in need['capabilities'] if state['capabilities'][c]['state']==UNSUPPORTED]
            if unsupported and not allow_fallback:raise ProviderError('MODEL_CAPABILITY_MISMATCH','手动模型不支持：'+','.join(unsupported)+'；未自动切换。')
            if state['availability']=='UNAVAILABLE' or unsupported:
                if not allow_fallback or not rows:raise ProviderError('MODEL_UNAVAILABLE','手动模型当前不可用；未发送请求或静默切换。')
                chosen=rows[0]
            else:chosen={'profile_id':pid,'reason':['用户手动指定；未知能力不作为已确认支持'],'snapshot':{'profile':self.catalog.profile(pid),'capabilities':self.catalog.test_result(pid),'request_seconds':120,'fingerprint':self.catalog.fingerprint(pid)}}
        chosen['snapshot']['request_seconds']=timeout
        resolved=chosen['snapshot']['profile']
        route={'mode':mode,'selection':selection,'allow_fallback':mode=='auto' or allow_fallback,'requirements':need,'current':chosen['profile_id'],'reason':chosen['reason'],'candidates':rows,'tried':[chosen['profile_id']],'tried_models':[[resolved['_connection']['connection_id'],resolved['model']]],'switches':[]}
        return chosen,route

def fallback(route,code,*,http_status=None,permit=True):
    # DNS/proxy/auth configuration failures must not be hidden by model rotation.
    allowed={'MODEL_QUOTA_EXHAUSTED','MODEL_NOT_FOUND','MODEL_TOOLS_UNAVAILABLE','MODEL_VISION_UNAVAILABLE','MODEL_CONTEXT_LIMIT','MODEL_REQUEST_TIMEOUT','OPENAI_COMPATIBLE_TIMEOUT','OPENAI_COMPATIBLE_REQUEST_FAILED'}
    if code=='OPENAI_COMPATIBLE_REQUEST_FAILED' and (http_status is None or http_status<500):return None
    if not route or not route.get('allow_fallback') or code not in allowed:return None
    rows=[r for r in route['candidates'] if r['profile_id'] not in route['tried'] and [r['snapshot']['profile']['_connection']['connection_id'],r['snapshot']['profile']['model']] not in route.get('tried_models',[])]
    if not rows:raise ProviderError('MODEL_CANDIDATES_EXHAUSTED','所有能力匹配候选均不可用；已保留任务、预算与执行证据，停止请求。')
    if not permit or len(route.get('switches',[]))>=3:raise ProviderError('MODEL_SWITCH_LIMIT','已达到本轮模型切换/重试上限（'+code+'）；任务和执行证据保留，未发送新请求。')
    chosen=rows[0];route['switches'].append({'from':route['current'],'to':chosen['profile_id'],'code':code,'at':time.time()});route['current']=chosen['profile_id'];route['tried'].append(chosen['profile_id']);route.setdefault('tried_models',[]).append([chosen['snapshot']['profile']['_connection']['connection_id'],chosen['snapshot']['profile']['model']]);route['reason']=['因 '+code+' 切换；保留原目标、工具证据、权限与预算',*chosen['reason']]
    return chosen
