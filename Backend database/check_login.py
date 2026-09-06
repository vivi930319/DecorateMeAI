#!/usr/bin/env python
import sys
import os

os.chdir('Backend database')
sys.path.insert(0, '.')

from app import app
import json

print("=" * 60)
print("登入診斷測試")
print("=" * 60)

with app.test_client() as client:
    # 測試登入
    print("\n1. 測試 POST /api/login")
    resp = client.post('/api/login',
                       data=json.dumps({
                           'email': 'admin@decorateme.local',
                           'password': 'admin123'
                       }),
                       content_type='application/json')

    print(f"   狀態碼: {resp.status_code}")
    print(f"   回應: {resp.get_json()}")

    if resp.status_code == 200:
        print("\n2. 檢查 Set-Cookie")
        cookie = resp.headers.get('Set-Cookie')
        if cookie:
            print(f"   ✓ 有 Set-Cookie")
            print(f"   {cookie[:100]}")
        else:
            print("   ✗ 沒有 Set-Cookie")

        print("\n3. 測試 GET /api/members/admin%40decorateme.local")
        resp2 = client.get('/api/members/admin%40decorateme.local')
        print(f"   狀態碼: {resp2.status_code}")
        print(f"   回應: {resp2.get_json()}")
    else:
        print("\n✗ 登入失敗，無法繼續測試")

print("\n" + "=" * 60)
