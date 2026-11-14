import importlib.util
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
import requests
from session_cookies import (GitHubCookieStore, split_accounts, parse_cookie,
    merge_response_cookies, same_cookie, mask_cookie)

ORIGIN = 'https://glados.cloud'
BJ = timezone(timedelta(hours=8))
def report(**data):
    print(json.dumps(data, ensure_ascii=False), flush=True)

def run():
    token = os.environ.pop('GH_TOKEN', '')
    original = split_accounts(os.environ.pop('GR_COOKIE', ''))
    agents = os.environ.pop('GR_USER_AGENT', '').splitlines()
    if not original or len(agents) not in (0, 1, len(original)):
        raise RuntimeError('configuration invalid')
    updated = list(original)
    for cookie in original:
        mask_cookie(cookie)
        for value in parse_cookie(cookie).values():
            print('::add-mask::' + value.replace('%','%25'), flush=True)
    store = GitHubCookieStore(os.environ['GITHUB_REPOSITORY'], 'GR_COOKIE', os.environ['GITHUB_RUN_ID'])
    def persist_call(fn, *args):
        os.environ['GH_TOKEN'] = token
        try:
            return fn(*args)
        finally:
            os.environ.pop('GH_TOKEN', None)
    persist_call(store.prepare)
    spec = importlib.util.spec_from_file_location('upstream', 'upstream_checkin.py')
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    upstream.DOMAINS = [ORIGIN]
    os.environ['EXCHANGE_PLAN'] = 'off'
    os.environ['CHECKIN_MAX_ATTEMPTS'] = '1'
    today = datetime.now(BJ).date()
    failures = 0
    for index, cookie in enumerate(original):
        os.environ['GLADOS_USER_AGENT'] = agents[index] if len(agents)>1 else (agents[0] if agents else '')
        client = upstream.GLaDOS(cookie)
        expected_email = None
        posts = 0
        def guarded(method, url, **kwargs):
            nonlocal posts, expected_email
            parsed = urlsplit(url)
            allowed = {'/api/user/status', '/api/user/points', '/api/user/checkin/challenge', '/api/user/checkin'}
            if parsed.scheme != 'https' or parsed.netloc != 'glados.cloud' or parsed.path not in allowed or parsed.query:
                raise RuntimeError('destination blocked')
            if method == 'POST':
                if parsed.path != '/api/user/checkin' or posts:
                    raise RuntimeError('extra POST blocked')
                posts += 1
            elif method != 'GET' or parsed.path == '/api/user/checkin':
                raise RuntimeError('method blocked')
            kwargs['allow_redirects'] = False
            kwargs['headers'] = dict(kwargs.get('headers', {}), Cookie=client.cookie)
            response = requests.request(method, url, **kwargs)
            if parsed.path == '/api/user/checkin/challenge' and response.status_code == 200:
                challenge = response.json()
                report(account=index+1, phase='challenge',
                       nonce_present=isinstance(challenge.get('nonce'), str),
                       turnstile_present=bool(challenge.get('turnstile')),
                       tsState_present='tsState' in challenge,
                       code=challenge.get('code') if type(challenge.get('code')) is int else None)
            candidate = merge_response_cookies(client.cookie, response, url)
            if not same_cookie(client.cookie, candidate):
                headers = dict(kwargs['headers'], Cookie=candidate)
                verify = requests.get(ORIGIN+'/api/user/status', headers=headers, timeout=10, allow_redirects=False)
                data = verify.json() if verify.status_code==200 else {}
                email = data.get('data',{}).get('email')
                if data.get('code') != 0 or not email or (expected_email and email != expected_email):
                    raise RuntimeError('rotated session identity verification failed')
                candidate = merge_response_cookies(candidate, verify, ORIGIN+'/api/user/status')
                before = list(updated)
                updated[index] = candidate
                persist_call(store.save, before, updated)
                store.updated_at = persist_call(store._gh, ['api', store.path, '--jq', '.updated_at'])
                client.cookie = candidate
                report(account=index+1, session_saved=True)
            return response
        class Transport:
            def __getattr__(self, name):
                if name in ('get', 'post'):
                    return lambda url, **kw: guarded(name.upper(), url, **kw)
                return getattr(requests, name)
        upstream.requests = Transport()
        try:
            state = client.req('GET','/api/user/status')
            expected_email = state.get('data',{}).get('email')
            if state.get('code') != 0 or not expected_email:
                report(account=index+1, status='authentication_failed', code=state.get('code'))
                failures += 1
                continue
            before = client.req('GET','/api/user/points')
            history = before.get('history')
            if not isinstance(history,list) or not history:
                report(account=index+1, status='cannot_confirm_today_skip')
                failures += 1
                continue
            recent = []
            for item in history:
                business = str(item.get('business',''))
                if 'checkin' not in business.lower():
                    continue
                stamp = item.get('time') or item.get('createdAt') or item.get('created_at')
                if isinstance(stamp,(int,float)):
                    dt = datetime.fromtimestamp(stamp/1000 if stamp>1e11 else stamp, timezone.utc)
                elif isinstance(stamp,str) and stamp.replace('.','',1).isdigit():
                    value = float(stamp)
                    dt = datetime.fromtimestamp(value/1000 if value>1e11 else value, timezone.utc)
                elif isinstance(stamp,str):
                    dt = datetime.fromisoformat(stamp.replace('Z','+00:00'))
                    if dt.tzinfo is None:
                        raise ValueError('ambiguous timestamp')
                else:
                    raise ValueError('unknown timestamp')
                recent.append({'time':dt.isoformat(),'change':float(item.get('change',0))})
            if not recent:
                report(account=index+1,status='no_identifiable_records_skip')
                failures += 1
                continue
            report(account=index+1, phase='before', points=before.get('points'), recent=recent[:3])
            if any(datetime.fromisoformat(x['time']).astimezone(BJ).date()==today and x['change']>0 for x in recent):
                report(account=index+1,status='already_signed_today_skip')
                continue
            result = client.checkin()
            code = result.get('code')
            reason = result.get('reason')
            message = str(result.get('message',''))
            category = ('cloudflare_verification_failed' if 'Cloudflare verification failed' in message else
                        'normal' if upstream.is_normal_checkin_result(result) else 'other_failure')
            report(account=index+1, phase='checkin', code=code if type(code) is int else None,
                   reason=reason if reason in ('device-mismatch','checkin-challenge-unavailable','checkin-challenge-expired','http-auth-rejected') else None,
                   category=category, posts=posts)
            after = client.req('GET','/api/user/points')
            report(account=index+1, phase='after', points=after.get('points'))
            if not upstream.is_normal_checkin_result(result):
                failures += 1
        except Exception as error:
            report(account=index+1, status='stopped', error_type=type(error).__name__, posts=posts)
            failures += 1
    return 1 if failures else 0

if __name__ == '__main__':
    try:
        sys.exit(run())
    except Exception as error:
        report(status='preflight_stopped', error_type=type(error).__name__)
        sys.exit(1)
