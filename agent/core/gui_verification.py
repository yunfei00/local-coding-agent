"""Independent GUI contract executed by TaskService, never by a second agent."""
import asyncio
import json
import re
import sys
import time

from agent.desktop.runtime import NAMES
from agent.tools.base import ToolError


def validate_gui(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'command', 'window_title', 'steps', 'timeout_seconds', 'vision_profile_id'}:
        raise ValueError('Invalid GUI verification contract')
    for key in ('command', 'window_title'):
        if not isinstance(value.get(key), str) or not 1 <= len(value[key].strip()) <= 2000:
            raise ValueError('GUI command and exact window_title are required')
    timeout = value.get('timeout_seconds', 120)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 5 <= timeout <= 300:
        raise ValueError('GUI timeout must be 5..300 seconds')
    steps = value.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise ValueError('GUI contract requires 1..20 bounded steps')
    for step in steps:
        if not isinstance(step, dict) or set(step) != {'tool', 'arguments'} or step['tool'] not in set(NAMES) - {'desktop_list_windows', 'desktop_screenshot'}:
            raise ValueError('GUI steps must use existing scoped desktop tools')
        if not isinstance(step['arguments'], dict) or set(step['arguments']) & {'window_id', 'share_with_model', 'timeout_seconds'}:
            raise ValueError('GUI window, upload and step limits are owned by the verifier')
        if len(json.dumps(step['arguments'], ensure_ascii=False)) > 8192:
            raise ValueError('GUI step arguments exceed 8 KiB')
        if step['tool'] == 'desktop_type_text':
            # Reject sensitive input before contracts enter persistent storage.
            text = step['arguments'].get('text')
            sensitive = r'password|passwd|token|secret|api.?key|credential|密码|口令|密钥|\b(?:sk-|ghp_|github_pat_|eyJ)[A-Za-z0-9_-]{12,}'
            selector = step['arguments'].get('selector', {})
            if not isinstance(text, str) or len(text) > 4000 or re.search(sensitive, text + json.dumps(selector, ensure_ascii=False), re.I):
                raise ValueError('GUI contracts accept ordinary non-secret fixture input only')
    assertions = [s for s in steps if s['tool'] == 'desktop_wait' and s['arguments'].get('state') in ('name', 'enabled', 'disabled', 'visible', 'hidden') and s['arguments'].get('selector')]
    if not assertions:
        raise ValueError('GUI contract needs an independent control state assertion')
    pid = value.get('vision_profile_id')
    if pid is not None and (not isinstance(pid, str) or not 1 <= len(pid) <= 100):
        raise ValueError('Invalid vision observer profile')
    return {**value, 'timeout_seconds': timeout}


def discover_gui(root, configured):
    if configured:
        return validate_gui(configured)
    path = root / '.lca' / 'gui-verification.json'
    if not path.exists():
        return None
    if not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 32768:
        raise ValueError('GUI verification file outside workspace or exceeds 32 KiB')
    return validate_gui(json.loads(path.read_text(encoding='utf-8')))


async def run_gui(contract, execute, tools, owner, observe=None, notify=None):
    """Fresh app each repair, immutable assertions, always close its owned process tree."""
    started = time.monotonic()
    evidence = []
    window = None
    process = None
    async def call(name, args):
        if notify:
            await notify('verification.progress', {'stage': name, 'state': 'running'})
        result = await execute(name, args)
        data = result.get('data') or {}
        evidence.append({'tool': name, 'ok': bool(result.get('ok')), 'error_code': (result.get('error') or {}).get('code'),
                         **({k:str(result[k])[-4000:] for k in ('stdout','stderr','summary') if k in result} if name == 'read_process' else {}),
                         **({'assertion': {k:args[k] for k in ('selector','state','expected') if k in args}} if name == 'desktop_wait' else {}),
                         **{k: data[k] for k in ('artifact_id', 'sha256', 'captured_at', 'path', 'window_generation') if k in data}})
        if notify:
            await notify('verification.progress', {'stage': name, 'state': 'completed', 'ok': bool(result.get('ok'))})
        if not result.get('ok'):
            raise ToolError((result.get('error') or {}).get('code', 'GUI_ASSERTION_FAILED'), 'Independent GUI action/assertion failed')
        return data
    try:
        if sys.platform != 'win32':
            raise ToolError('DESKTOP_UNSUPPORTED', 'Independent GUI acceptance requires an interactive Windows desktop')
        async with asyncio.timeout(contract['timeout_seconds']):
            process = await call('start_process', {'command': contract['command'], 'timeout_seconds': contract['timeout_seconds']})
            session = tools.processes.sessions[process['process_id']]
            deadline = time.monotonic() + min(30, contract['timeout_seconds'])
            window = None
            while time.monotonic() < deadline:
                listed = await call('desktop_list_windows', {'timeout_seconds': 10})
                matches = [w for w in listed['windows'] if w['title'] == contract['window_title'] and session.job.contains(w['pid'])]
                if len(matches) > 1:
                    raise ToolError('GUI_WINDOW_AMBIGUOUS', 'More than one owned window matches')
                if matches:
                    window = matches[0]['window_id']
                    break
                await asyncio.sleep(.2)
            if not window:
                raise ToolError('GUI_WINDOW_NOT_FOUND', 'No exact window in the launched process tree')
            await call('desktop_inspect', {'window_id': window, 'timeout_seconds': 15})
            for step in contract['steps']:
                await call(step['tool'], {**step['arguments'], 'window_id': window, 'timeout_seconds': 40})
            await call('desktop_screenshot', {'window_id': window, 'share_with_model': bool(observe), 'timeout_seconds': 15})
            if observe:
                # The screenshot call above must pass M3's separate upload approval.
                observation = await observe(tools.desktop.image_message(owner))
                evidence.append({'tool': 'vision_observer', 'observation': observation})
                if observation['errors']:
                    raise ToolError('VISION_REPORTED_ERROR', 'Visual observation found an error; untrusted evidence returned to controller')
        ok, code = True, None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        ok, code = False, 'GUI_TIMEOUT' if isinstance(exc, TimeoutError) else getattr(exc, 'code', type(exc).__name__)
        if process:
            try:
                async with asyncio.timeout(5):
                    await call('read_process', {'process_id': process['process_id'], 'cursor': 0, 'wait_seconds': 0})
            except Exception:
                pass
        if window and code not in ('APPROVAL_DENIED', 'PERMISSION_DENIED'):
            try:
                async with asyncio.timeout(15):
                    await call('desktop_screenshot', {'window_id': window, 'timeout_seconds': 10})
            except Exception:
                pass
    finally:
        await tools.desktop.close_owner(owner)
        await tools.processes.close_owner(owner)
    category = 'passed' if ok else 'assertion'
    if code in ('APPROVAL_DENIED', 'PERMISSION_DENIED'):
        category = 'permission'
    elif code in ('GUI_TIMEOUT', 'DESKTOP_TIMEOUT', 'MODEL_TIMEOUT'):
        category = 'timeout'
    elif code in ('DESKTOP_UNSUPPORTED', 'DESKTOP_WORKER_FAILED'):
        category = 'environment'
    elif code in ('BUDGET_EXHAUSTED', 'MODEL_INVALID_RESULT', 'VISION_SCHEMA_INVALID', 'VISION_UNEXPECTED_TOOL', 'VISION_IMAGE_MISSING'):
        category = 'configuration'
    elif code and code.startswith('OPENAI_COMPATIBLE_'):
        category = 'network'
    return {'command': 'GUI acceptance', 'ok': ok, 'category': category,
            'exit_code': 0 if ok else 1, 'duration_ms': round((time.monotonic()-started)*1000),
            'summary': 'Independent desktop assertions passed' if ok else 'Independent GUI verification failed: ' + str(code),
            'error_code': code, 'evidence': evidence}
