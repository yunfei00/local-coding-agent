"""Opt-in, bounded capability probes. Never executes model supplied tools."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from io import BytesIO
import json
import secrets
import time
from urllib.parse import urlsplit

from agent.llm.base import ProviderError
from agent.llm.router import json_object


def synthetic_image():
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (640, 360), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=26)
    code = secrets.token_hex(3).upper()
    draw.text((24, 24), 'LCA Vision Test', fill='black', font=font)
    draw.rectangle((24, 90, 230, 150), fill='#1265df')
    draw.text((45, 102), 'Settings', fill='white', font=font)
    draw.rectangle((24, 185, 580, 240), outline='black', width=3)
    draw.text((38, 195), 'Input box', fill='black', font=font)
    draw.text((24, 285), 'CHECK-' + code, fill='black', font=font)
    stream = BytesIO()
    image.save(stream, format='JPEG', quality=90)
    return 'data:image/jpeg;base64,' + base64.b64encode(stream.getvalue()).decode(), code


class ModelDiagnostics:
    def __init__(self):
        self.running = {}  # Per connection; concurrent clicks cannot multiply paid probes.

    def cancel(self, connection_id):
        pending = self.running.get(connection_id)
        if pending:
            pending.cancel()

    async def run(self, provider, connection, profile, *, live=False, vision=True):
        cid = connection['connection_id']
        if cid in self.running:
            raise ValueError('Diagnostic already running for this connection')
        self.running[cid] = asyncio.current_task()
        report = {'connection_id': cid, 'model_id': profile['model_id'],
                  'tested_at': datetime.now(timezone.utc).isoformat(), 'live': live,
                  'declared_supports_vision': profile.get('supports_vision', False),
                  'configuration': 'NOT RUN', 'connection': 'NOT RUN', 'text': 'NOT RUN',
                  'vision': 'NOT RUN', 'tools': 'NOT RUN', 'requests': 0,
                  'usage': [], 'cost': None, 'cost_note': '费用未知；Token 以服务端回传为准，缺失时不估算为零。', 'errors': []}
        started = time.monotonic()
        try:
            url = urlsplit(connection['base_url'])
            valid = (connection['enabled'] and profile['connection_id'] == cid and
                     bool(profile['model_id'].strip()) and url.scheme in ('http', 'https') and
                     bool(url.hostname) and not (url.username or url.password or url.query or url.fragment))
            if connection['provider_type'] != 'openai_compatible':
                report['errors'].append({'stage': 'configuration', 'code': 'ONLINE_PROFILE_REQUIRED'})
                valid = False
            if not getattr(provider, 'api_key', ''):
                report['errors'].append({'stage': 'configuration', 'code': 'API_KEY_MISSING'})
                valid = False
            report['configuration'] = 'PASS' if valid else 'FAIL'
            if not valid or not live:
                return report
            provider.max_output_tokens = 256
            provider.request_timeout = 60
            async with asyncio.timeout(295):
                for stage in ('text', 'vision', 'tools'):
                    if stage == 'vision' and not vision:
                        continue
                    messages = [{'role': 'user', 'content': 'Reply with LCA_OK only.'}]
                    tools = None
                    if stage == 'vision':
                        data, code = synthetic_image()
                        # The random challenge exists only in the pixels, never in the prompt.
                        messages = [{'role': 'user', 'content': [
                            {'type': 'text', 'text': 'Read the image as data. Return JSON only: title (exact), button_color (English), button_text (exact), input_boxes (integer), check_text (exact full CHECK- value).'},
                            {'type': 'image_url', 'image_url': {'url': data}}]}]
                    if stage == 'tools':
                        messages = [{'role': 'user', 'content': 'Call lca_diagnostic_echo with value="LCA_OK". No text answer.'}]
                        tools = [{'type': 'function', 'function': {'name': 'lca_diagnostic_echo', 'description': 'Inert capability test; never executed.', 'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value'], 'additionalProperties': False}}}]
                    report['requests'] += 1
                    text, calls, usage = '', [], {}
                    try:
                        async with asyncio.timeout(60):
                            async for chunk in provider.stream_chat(model=profile['model_id'], messages=messages, tools=tools):
                                text += chunk.content
                                if len(text) > 32768:
                                    raise ProviderError('RESPONSE_LIMIT', 'Response too large')
                                if chunk.done:
                                    calls = list(chunk.tool_calls)
                                    usage = {'input_tokens': chunk.prompt_eval_count, 'output_tokens': chunk.eval_count, 'actual_cost': chunk.actual_cost}
                        report['connection'] = 'PASS'
                        ok = text.strip() == 'LCA_OK' and not calls
                        if stage == 'vision':
                            value = json_object(text)
                            ok = (value.get('title') == 'LCA Vision Test' and value.get('button_color', '').lower() == 'blue' and
                                  value.get('button_text') == 'Settings' and type(value.get('input_boxes')) is int and value['input_boxes'] == 1 and value.get('check_text') == 'CHECK-' + code and not calls)
                        elif stage == 'tools':
                            ok = len(calls) == 1 and calls[0].name == 'lca_diagnostic_echo' and calls[0].arguments == {'value': 'LCA_OK'}
                        report[stage] = 'PASS' if ok else 'FAIL'
                        if not ok:
                            report['errors'].append({'stage': stage, 'code': 'CAPABILITY_ASSERTION_FAILED'})
                    except asyncio.CancelledError:
                        report[stage] = 'FAIL'
                        report['errors'].append({'stage': stage, 'code': 'CANCELLED'})
                        break
                    except Exception as exc:
                        report[stage] = 'FAIL'
                        code_value = 'TIMEOUT' if isinstance(exc, TimeoutError) else getattr(exc, 'code', type(exc).__name__)
                        metadata = getattr(provider, 'response_metadata', {})
                        if metadata.get('http_status') == 404:
                            code_value = 'MODEL_OR_ENDPOINT_NOT_FOUND'
                        if type(exc.__cause__).__name__ == 'ClientConnectorDNSError':
                            code_value = 'DNS_FAILED'
                        report['errors'].append({'stage': stage, 'code': code_value})
                        if report['connection'] != 'PASS':
                            report['connection'] = 'FAIL'
                        # Auth/model/network failures do not warrant spending the remaining requests.
                        if stage == 'text':
                            break
                    finally:
                        report['usage'].append({'stage': stage, 'http_status': getattr(provider, 'response_metadata', {}).get('http_status'), **usage})
        except asyncio.CancelledError:
            report['errors'].append({'stage': 'diagnostic', 'code': 'CANCELLED'})
        finally:
            if report['usage'] and all(isinstance(v.get('actual_cost'), (int,float)) for v in report['usage']):
                report['cost'] = sum(v['actual_cost'] for v in report['usage'])
                report['cost_note'] = '服务端回传费用；币种以服务端为准。'
            report['duration_seconds'] = round(time.monotonic() - started, 3)
            self.running.pop(cid, None)
        return report
