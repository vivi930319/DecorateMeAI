"""Read-only live Gateway acceptance. No secrets or response bodies in reports."""
import argparse
import getpass
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx


def check_contract(status, content_type, body, expected, kind=None):
    if status != expected:
        return False, f'HTTP {status}; expected {expected}'
    if 'application/json' not in content_type.lower() or not isinstance(body, dict):
        return False, 'Response is not a JSON object'
    if expected >= 400:
        detail = body.get('detail')
        error = body.get('error') or (detail.get('error') if isinstance(detail, dict) else None)
        if not isinstance(error, dict) or not error.get('code'):
            return False, 'Missing structured error code'
    if kind == 'config' and (body.get('memberDatabaseUrl') != '/member-database'
                             or body.get('productUrl') != '/product-api'):
        return False, 'Public config must expose same-origin proxy paths'
    if kind == 'products':
        items = body.get('products', body.get('items'))
        total = body.get('total')
        if not isinstance(items, list) or not isinstance(total, int) or total < len(items):
            return False, 'Invalid product list/total contract'
        if len(items) > 100:
            return False, 'Page size exceeds requested limit'
    if kind == 'members' and not isinstance(body.get('members'), list):
        return False, 'Missing members[]'
    return True, 'Contract matched'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='https://decorate-me.web.app')
    parser.add_argument('--roles', action='store_true', help='Prompt securely for member/admin __session values')
    parser.add_argument('--output', default='gateway-acceptance.json')
    parser.add_argument('--budget-ms', type=int, default=2000, help='Provisional first-page response budget')
    args = parser.parse_args()
    base = args.base.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        parser.error('--base must be an HTTPS origin without credentials, path or query')
    if args.budget_ms <= 0:
        parser.error('--budget-ms must be positive')
    rows = []

    def probe(client, name, route, expected, kind=None, headers=None):
        started = time.perf_counter()
        try:
            response = client.get(route, headers=headers)
            try:
                body = response.json()
            except ValueError:
                body = None
            ok, detail = check_contract(response.status_code, response.headers.get('content-type', ''), body, expected, kind)
            elapsed = round((time.perf_counter() - started) * 1000)
            row = dict(test=name, result='PASS' if ok else 'FAIL', http=response.status_code,
                       ms=elapsed, bytes=len(response.content), detail=detail)
            if kind == 'products' and ok and elapsed > args.budget_ms:
                row.update(result='FAIL', detail='Product page exceeded configured latency budget')
            rows.append(row)
            return body if ok else None
        except httpx.HTTPError as exc:
            rows.append(dict(test=name, result='FAIL', detail=type(exc).__name__))
            return None

    def client():
        # Never follow redirects carrying a session; never disable TLS verification.
        return httpx.Client(base_url=base, timeout=30, follow_redirects=False)

    with client() as public:
        probe(public, 'public-config', '/public-config', 200, 'config')
        probe(public, 'anonymous-roster-denied', '/member-database/api/members', 401)
        probe(public, 'anonymous-admin-feedback-denied', '/admin-api/face-feedback', 401)
        probe(public, 'spoofed-admin-denied', '/member-database/api/members', 401,
              headers={'X-Admin-Request': '1', 'X-User-Role': 'admin', 'X-Gateway-Key': 'not-a-real-key'})
        probe(public, 'invalid-session-denied', '/member-database/api/members', 401,
              headers={'Cookie': '__session=invalid-test-token'})
        for i in range(3):
            probe(public, f'product-page-{i+1}', '/product-api/api/products?limit=100', 200, 'products')

    for role in ('member', 'admin'):
        if not args.roles:
            rows.append(dict(test=f'{role}-authenticated-flow', result='SKIP', detail='No test session supplied'))
            continue
        print(f'Only paste a dedicated {role} test account __session VALUE for {base}. Input is hidden.')
        cookie = getpass.getpass(f'{role} __session: ').strip()
        if not cookie or any(c in cookie for c in '\r\n;'):
            rows.append(dict(test=f'{role}-session', result='FAIL', detail='Empty or invalid cookie input'))
            continue
        with client() as authenticated:
            authenticated.cookies.set('__session', cookie, domain=parsed.hostname, path='/')
            cookie = None
            session = probe(authenticated, f'{role}-session', '/auth/session', 200)
            if not session or session.get('ok') is not True or session.get('role') != role or not session.get('actorId') or not session.get('sub'):
                rows.append(dict(test=f'{role}-identity', result='FAIL', detail='Required account role/identity not verified; subsequent tests blocked'))
                continue
            headers = {'X-Expected-Actor': session['actorId']}
            probe(authenticated, f'{role}-roster', '/member-database/api/members', 200 if role == 'admin' else 403,
                  'members' if role == 'admin' else None, headers)
            if role == 'member':
                own = quote(session['sub'], safe='')
                probe(authenticated, 'member-own-profile', f'/member-database/api/members/{own}', 200, headers=headers)
                probe(authenticated, 'member-cross-account-denied', '/member-database/api/members/gateway-negative-test%40example.invalid', 403, headers=headers)

    counts = {state: sum(r['result'] == state for r in rows) for state in ('PASS', 'FAIL', 'SKIP')}
    result = 'FAIL' if counts['FAIL'] else 'INCOMPLETE' if counts['SKIP'] else 'PASS'
    report = dict(time=datetime.now(timezone.utc).isoformat(), base=base, scope='read-only API acceptance; not browser or training UAT',
                  result=result, counts=counts, checks=rows)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in rows:
        print(f"{row['result']:4} {row['test']}: {row['detail']}")
    print(f'{result}: {counts}; report={args.output}')
    return 1 if result == 'FAIL' else 2 if result == 'INCOMPLETE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
