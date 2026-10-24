"""Bounded live acceptance through the production Electron IPC and TaskService.

Offline inventory by default. Never reads/decrypts a protected credential itself.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.core.model_catalog import KEY, validate_catalog
from agent.core.verification import acceptance_changes
from agent.llm.router import validate_config
from agent.persistence.store import SQLiteStore

REPORT = ROOT / 'validation-reports/real-online-agent-acceptance.json'
SESSION = REPORT.with_name('real-online-agent-session.json')


def allocate_session(path, model, requested_calls, requested_tokens=60000, attempt_limit=2, update=False, requested_seconds=900):
    """One bounded acceptance session, including retries and both model groups.

    A controller crash keeps the full allocation reserved rather than resetting
    paid-call counters. Deleting reports is never part of the acceptance command.
    """
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
        'call_ceiling': min(12, requested_calls), 'attempts': []}
    state.setdefault('token_ceiling',60000)
    state.setdefault('seconds_ceiling',900)
    state.setdefault('attempt_limits',{})
    attempts = state['attempts']
    if any(a['state'] == 'reserved' for a in attempts):
        raise ValueError('PREVIOUS_ATTEMPT_UNSETTLED: no automatic retry or reservation refund')
    if update:
        if not 1 <= requested_calls <= 10000 or not 1 <= requested_tokens <= 1000000000 or not 1 <= attempt_limit <= 10 or not 1 <= requested_seconds <= 7200:
            raise ValueError('INVALID_EXPLICIT_SESSION_CAPS')
        previous = {'calls':state['call_ceiling'],'tokens':state['token_ceiling'],
                    'attempts':state['attempt_limits'].get(model,2)}
        previous_seconds=state['seconds_ceiling']
        state.update(call_ceiling=requested_calls,token_ceiling=requested_tokens)
        state['seconds_ceiling']=requested_seconds
        state['attempt_limits'][model] = attempt_limit
        state.setdefault('budget_updates',[]).append({'at':datetime.now(timezone.utc).isoformat(),
            'authorization':'explicit_cli_budget_update','previous':previous,
            'new':{'calls':requested_calls,'tokens':requested_tokens,'attempts':attempt_limit},
            'previous_seconds':previous_seconds,'new_seconds':requested_seconds,
            'used_calls':sum(a['calls'] for a in attempts),'used_tokens':sum(a['tokens'] for a in attempts)})
    if sum(a['model'] == model and bool(a.get('task_id')) for a in attempts) >= state['attempt_limits'].get(model,2):
        raise ValueError('FULL_RETRY_LIMIT_REACHED')
    if model == 'glm-5.3' and not any(a['model'] == 'qwen3.8-flash' and a.get('result') == 'PASS' for a in attempts):
        raise ValueError('QWEN_ACCEPTANCE_REQUIRED_BEFORE_GLM')
    remaining = {'calls': min(requested_calls, state['call_ceiling'] - sum(a['calls'] for a in attempts)),
                 'tokens': min(requested_tokens,state['token_ceiling'] - sum(a['tokens'] for a in attempts)),
                 'seconds': int(state['seconds_ceiling'] - sum(a['seconds'] for a in attempts))}
    if any(v <= 0 for v in remaining.values()):
        raise ValueError('LIVE_SESSION_BUDGET_EXHAUSTED')
    attempts.append({'model': model, 'state': 'reserved', **remaining})
    path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    return remaining


def settle_session(path, report):
    state = json.loads(path.read_text(encoding='utf-8'))
    attempt = state['attempts'][-1]
    usage = report.get('usage') or {}
    # Missing task ID alone is insufficient: task.start may have reached the
    # backend before the controller lost its reply. Refund only known preflight
    # failures or a terminal task with settled, numeric usage.
    safe_preflight=(not report.get('task_id') and report.get('controller_stage') in {
        'electron_launch','electron_window','agent_ready','protected_credential_status','project_and_thread'})
    settled_task=(report.get('task_id') and report.get('final_status') in {
        'paused','failed','cancelled','completed','awaiting_approval'} and not report.get('usage_uncertain')
        and isinstance(usage.get('api_calls'),int) and isinstance(usage.get('reserved_tokens'),int))
    if safe_preflight or settled_task:
        attempt.update(state='settled', calls=0 if safe_preflight else usage['api_calls'],
                       tokens=0 if safe_preflight else usage['reserved_tokens'], seconds=report.get('active_seconds', 0) or 0,
                       result=report['result'], task_id=report.get('task_id'))
    path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    report['session'] = state
    archive = REPORT.with_name(f'real-online-agent-attempt-{len(state["attempts"])}.json')
    archive.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def load_catalog(data: Path):
    db = data / 'local-coding-agent.sqlite3'
    if not db.is_file():
        raise ValueError('SAVED_CATALOG_UNAVAILABLE')
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        row = connection.execute('SELECT value FROM settings WHERE key=?', (KEY,)).fetchone()
    if not row:
        raise ValueError('SAVED_CATALOG_UNAVAILABLE')
    return validate_catalog(json.loads(row[0]))


def select_profile(catalog, model, explicit=None, *, vision=False):
    enabled = {c['connection_id'] for c in catalog['connections']
               if c['enabled'] and c['provider_type'] == 'openai_compatible'}
    candidates = [p for p in catalog['profiles'] if p['connection_id'] in enabled
                  and p['model_id'] == model and (not explicit or p['model_profile_id'] == explicit)]
    if len(candidates) != 1:
        raise ValueError('PROFILE_MISSING_OR_AMBIGUOUS: ' + model)
    profile = candidates[0]
    if vision and not profile.get('supports_vision'):
        raise ValueError('VISION_CAPABILITY_NOT_DECLARED')
    return profile


def live_config(executor, vision, calls, tokens=60000, extended=False):
    if isinstance(calls, bool) or not isinstance(calls, int) or not 1 <= calls <= 10000:
        raise ValueError('Live acceptance allows 1..10000 calls')
    # Currency/price units are not recorded in old profiles. Do not invent CNY
    # pricing or claim a monetary hard cap. Use a stricter request ceiling.
    if calls > 12 and not extended:
        raise ValueError('UNVERIFIED_CNY_PRICING: maximum 12 calls, no automatic increase')
    if isinstance(tokens,bool) or not isinstance(tokens,int) or not 1 <= tokens <= (1000000000 if extended else 60000):
        raise ValueError('INVALID_LIVE_TOKEN_LIMIT')
    return validate_config({'strategy': 'single-agent',
        'roles': {r: {'model_profile_id': executor['model_profile_id']}
                  for r in ('planner', 'executor', 'reviewer', 'escalation')},
        'vision_profile_id': vision['model_profile_id'],
        'budget': {'api_calls': calls, 'global_api_calls': calls,
                   'api_tokens': tokens, 'global_api_tokens': tokens,
                   'request_seconds': 60, 'task_seconds': 900, 'local_repairs': 3}})


def prepare(source_data, catalog, executor, vision, calls, temporary, *, tokens=60000, extended=False):
    """Copy only public model metadata, preserving the original credential context.

    No user database/messages/secret files are copied. The real Electron main
    process uses its existing userData safeStorage context and synchronization
    IPC; its Agent database is separately isolated with LCA_DATA_DIR.
    """
    temporary = Path(temporary)
    data = temporary / 'data'
    data.mkdir()
    source = temporary / 'fixture'
    shutil.copytree(ROOT / 'manual-fixtures/m5-electron-e2e', source,
                    ignore=shutil.ignore_patterns('node_modules', 'dist', '.runtime'))
    for args in (['init', '-q', '-b', 'main'], ['config', 'user.name', 'Live acceptance'],
                 ['config', 'user.email', 'acceptance@example.test'], ['add', '.'],
                 ['commit', '-qm', 'Unrepaired M5 fixture baseline']):
        subprocess.run(['git', *args], cwd=source, check=True, capture_output=True)
    selected = {executor['model_profile_id'], vision['model_profile_id']}
    profiles = [p for p in catalog['profiles'] if p['model_profile_id'] in selected]
    connections = [c for c in catalog['connections']
                   if c['connection_id'] in {p['connection_id'] for p in profiles}]
    config = live_config(executor, vision, calls,tokens,extended)
    store = SQLiteStore(data)
    try:
        store.set_setting(KEY, json.dumps({'connections': connections, 'profiles': profiles}))
        store.set_setting('orchestration.config', json.dumps(config))
        store.set_setting('chat.default_profile_id', executor['model_profile_id'])
    finally:
        store.connection.close()
    manifest = {'source': str(source), 'data': str(data), 'config': config,
                'credential_data': str(source_data.resolve()),
                'executor': {k: executor[k] for k in ('model_profile_id', 'connection_id', 'model_id')},
                'vision': {k: vision[k] for k in ('model_profile_id', 'connection_id', 'model_id')},
                'report': str(REPORT), 'call_limit': calls}
    path = temporary / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return path


def run_controller(command, env, timeout=1020):
    """Reuse the product kill-on-close Job even if the controller itself hangs."""
    from agent.tools.windows_job import WindowsJob
    child = subprocess.Popen(command, cwd=ROOT, env=env,
        creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 4) if os.name == 'nt' else 0)
    job = None
    try:
        job = WindowsJob(child.pid)
        job.resume(child.pid)
        return child.wait(timeout=timeout)
    finally:
        try:
            if job:
                job.terminate_and_wait_sync()
        finally:
            if job:
                job.close()
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def verify_disk(report):
    """Independent read-only evidence, never changes the experimental source."""
    source, workspace = report.get('source'), report.get('workspace')
    if not source or not workspace:
        return
    source, workspace = Path(source), Path(workspace)
    unchanged = subprocess.run(['git', 'status', '--porcelain'], cwd=source,
                               capture_output=True, text=True, check=True).stdout == ''
    baseline = report.pop('acceptance_baseline', {})
    changed = acceptance_changes(workspace, baseline) if baseline else ['MISSING_BASELINE']
    diff = subprocess.run(['git', 'diff', '--', '.', ':!package-lock.json'], cwd=workspace,
                          capture_output=True, text=True, encoding='utf-8', check=True).stdout
    report['disk_evidence'] = {'source_unchanged': unchanged,
        'acceptance_changes': changed, 'diff': diff[:24000], 'diff_truncated': len(diff) > 24000,
        'app_sha256': hashlib.sha256((workspace / 'src/App.tsx').read_bytes()).hexdigest()}
    saved = workspace / '.runtime/saved.json'
    report['disk_evidence']['persisted_value'] = json.loads(saved.read_text()).get('value') if saved.exists() else None
    artifact_root = (source.parent / 'data/desktop-artifacts').resolve()
    local_artifacts = REPORT.parent / 'real-online-local-artifacts'
    retained = []
    for round_ in report.get('verification_history') or []:
        for result in round_.get('results', []):
            for evidence in result.get('evidence', []):
                if evidence.get('tool') != 'desktop_screenshot' or not evidence.get('ok'):
                    continue
                capture = Path(evidence.get('path','')).resolve()
                if capture.is_relative_to(artifact_root) and capture.is_file() and capture.suffix == '.png':
                    local_artifacts.mkdir(exist_ok=True)
                    target = local_artifacts / capture.name
                    shutil.copy2(capture,target)
                    retained.append({'artifact_id':evidence.get('artifact_id'),
                        'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'local_path':str(target)})
    report['controlled_local_artifacts'] = retained
    # This isolated backend serves one Task only. Every screenshot is approved
    # for the exact fixture PID/title, including model-led captures before the
    # independent verifier is reached. Preserve those too on a failed attempt.
    approved=any(a.get('tool')=='desktop_screenshot' and a.get('decision')=='allow_once' for a in report.get('approvals',[]))
    if approved and report.get('task_id'):
        from PIL import Image
        known={a['local_path'] for a in retained}
        wire_hashes={image['sha256'] for call in report.get('calls',[]) for image in call.get('wire_images',[])}
        for capture in artifact_root.rglob('capture_*.png'):
            if not capture.resolve().is_relative_to(artifact_root) or capture.stat().st_size>32*1024*1024:
                continue
            local_artifacts.mkdir(exist_ok=True)
            target=local_artifacts/capture.name
            if str(target) in known:
                continue
            shutil.copy2(capture,target)
            with Image.open(target) as pixels:
                pixels=pixels.convert('RGB');pixels.thumbnail((768,768));encoded=BytesIO()
                pixels.save(encoded,format='JPEG',quality=65)
            wire_hash=hashlib.sha256(encoded.getvalue()).hexdigest()
            retained.append({'artifact_id':capture.stem,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                             'local_path':str(target),'wire_jpeg_sha256':wire_hash,'wire_request_matched':wire_hash in wire_hashes})
    report['process_cleanup_metadata']=[]
    for metadata in (source.parent/'data/command-logs').glob('*/process.json'):
        value=json.loads(metadata.read_text(encoding='utf-8'))
        if Path(value.get('workspace','')).resolve().is_relative_to(source.parent.resolve()):
            report['process_cleanup_metadata'].append({k:value.get(k) for k in (
                'process_id','pid','state','exit_code','error','cleanup_stage','cleanup_detail','cleanup_reason','job_cleanup',
                'started_at','ended_at','duration_ms')})
    if report.get('result') == 'PASS' and (not unchanged or changed or not diff.strip()
            or report['disk_evidence']['persisted_value'] != 'M5 verified B'):
        report['result'] = 'FAIL'
        report['reason'] = 'INDEPENDENT_DISK_EVIDENCE_FAILED'


def write_report(report):
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 真实在线 Agent 验收', '', f"结果：{report['result']}",
             f"原因：{report.get('reason', '')}", '',
             '真实推理与 Mock 回归分别报告；没有请求不计为在线通过。', '',
             '费用未知：默认最多 12 次；只有明确授权的额度更新才能提高，上限及既有用量见 session。', '',
             '```json', json.dumps({k:v for k,v in report.items() if k not in ('tools','disk_evidence','verification_history')},
                                 ensure_ascii=False, indent=2), '```']
    REPORT.with_suffix('.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.getenv('APPDATA', str(Path.home()))) / 'local-coding-agent-desktop')
    parser.add_argument('--live', action='store_true', help='Authorize paid requests and controlled M5 GUI operations')
    parser.add_argument('--model', choices=('qwen3.8-flash', 'qwen3.8-max', 'glm-5.3'), default='qwen3.8-flash')
    parser.add_argument('--vision-model', choices=('qwen3.8-flash','qwen3.8-max'))
    parser.add_argument('--executor-profile')
    parser.add_argument('--vision-profile')
    parser.add_argument('--max-calls', type=int, default=12)
    parser.add_argument('--max-tokens', type=int, default=60000)
    parser.add_argument('--max-full-attempts', type=int, default=2)
    parser.add_argument('--max-seconds', type=int, default=900)
    parser.add_argument('--authorize-budget-update', action='store_true',help='Explicit user authorization required; preserves all prior usage')
    args = parser.parse_args()
    allocated = False
    controller_started = False
    report = {'result': 'NOT RUN', 'os': platform.platform(),
              'main_start_sha': subprocess.check_output(['git','rev-parse','origin/main'],cwd=ROOT,text=True).strip(),
              'paid_requests': 0, 'cost': 'UNKNOWN', 'interactive_desktop': False}
    try:
        catalog = load_catalog(args.data_dir)
        executor = select_profile(catalog, args.model, args.executor_profile)
        vision_model = args.vision_model or ('qwen3.8-flash' if args.model == 'glm-5.3' else args.model)
        vision = select_profile(catalog, vision_model, args.vision_profile, vision=True)
        config = live_config(executor, vision, args.max_calls,args.max_tokens,args.authorize_budget_update)
        report.update(executor={k:executor[k] for k in ('model_profile_id','connection_id','model_id')},
                      vision={k:vision[k] for k in ('model_profile_id','connection_id','model_id')}, limits=config['budget'])
        from agent.desktop.session import require_interactive_session
        require_interactive_session()
        report['interactive_desktop'] = True
        if not args.live:
            report['reason'] = 'OFFLINE_PREFLIGHT_ONLY; use --live for explicitly bounded paid acceptance'
        else:
            # Fresh isolated state, ordinary execution budget defaults preserved.
            with tempfile.TemporaryDirectory(prefix='lca-live-m5-') as temporary:
                REPORT.parent.mkdir(exist_ok=True)
                remaining = allocate_session(SESSION, args.model, args.max_calls,args.max_tokens,
                                             args.max_full_attempts,args.authorize_budget_update,args.max_seconds)
                allocated = True
                manifest = prepare(args.data_dir, catalog, executor, vision, remaining['calls'], temporary,
                                   tokens=remaining['tokens'],extended=args.authorize_budget_update)
                document = json.loads(manifest.read_text(encoding='utf-8'))
                document['config']['budget'].update(api_tokens=remaining['tokens'],global_api_tokens=remaining['tokens'],task_seconds=remaining['seconds'])
                if args.authorize_budget_update:
                    # Latest user authorization: large run-specific bounds,
                    # while original repetition, failure and approval guards stay.
                    document['execution_overrides']={'LCA_EXECUTION_TOKENS':str(remaining['tokens']),
                        'LCA_EXECUTION_SECONDS':str(remaining['seconds']),
                        'LCA_EXECUTION_MODEL_CALLS':str(min(512,remaining['calls'])),
                        'LCA_MAX_MODEL_STEPS':str(min(100,remaining['calls'])),'LCA_MAX_TOOL_CALLS':'512'}
                # Settings and Task both receive the reduced remaining global cap.
                isolated = SQLiteStore(Path(temporary)/'data')
                isolated.set_setting('orchestration.config',json.dumps(document['config']))
                isolated.connection.close()
                manifest.write_text(json.dumps(document),encoding='utf-8')
                report['limits'] = document['config']['budget']
                report['execution_overrides']=document.get('execution_overrides',{})
                write_report(report)
                env = {k:v for k,v in os.environ.items() if not k.startswith('LCA_') and k != 'ELECTRON_RUN_AS_NODE'}
                env.update(PYTHONUTF8='1')
                controller_started = True
                exit_code = run_controller(['node', str(Path(__file__).with_suffix('.cjs')), str(manifest)],env,
                                          timeout=remaining['seconds']+120)
                report = json.loads(REPORT.read_text(encoding='utf-8'))
                verify_disk(report)
                if exit_code and report['result'] == 'PASS':
                    report.update(result='FAIL', reason='CONTROLLER_EXIT_FAILED')
    except Exception as exc:
        # No traceback/request objects/environment dump (may contain secrets).
        if controller_started and REPORT.exists():
            recorded = json.loads(REPORT.read_text(encoding='utf-8'))
            report = recorded
        report.update(result='FAIL' if report.get('task_id') else 'NOT RUN',
                      reason=getattr(exc,'code',str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
    if allocated:
        settle_session(SESSION, report)
    write_report(report)
    print(json.dumps({k:report.get(k) for k in ('result','reason','paid_requests','task_id','final_status')}, ensure_ascii=False))
    return 0 if report['result'] == 'PASS' or (not args.live and report['interactive_desktop']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
