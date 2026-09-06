#!/usr/bin/env python
"""測試 Cookie 設定"""
import sys
import os
import json

os.chdir('Backend database')
sys.path.insert(0, '.')

# 寫入測試結果
with open('cookie_test_result.txt', 'w', encoding='utf-8') as result:
    result.write("開始測試...\n")

    try:
        from app import app

        result.write("✓ App 載入成功\n")

        with app.test_client() as client:
            result.write("✓ Test client 建立成功\n")

            # 測試登入
            resp = client.post('/api/login',
                               data=json.dumps({
                                   'email': 'admin@decorateme.local',
                                   'password': 'admin123'
                               }),
                               content_type='application/json')

            result.write(f"\n登入狀態碼: {resp.status_code}\n")
            result.write(f"登入回應: {resp.get_json()}\n")

            # 檢查所有 headers
            result.write(f"\n所有 Headers:\n")
            for key, value in resp.headers:
                result.write(f"  {key}: {value}\n")

            # 特別檢查 Set-Cookie
            set_cookie = resp.headers.get('Set-Cookie')
            if set_cookie:
                result.write(f"\n✓ Set-Cookie 存在:\n")
                result.write(f"  {set_cookie}\n")
            else:
                result.write(f"\n✗ Set-Cookie 不存在！\n")

            # 測試第二個請求（使用 Cookie）
            if set_cookie:
                result.write(f"\n測試第二個請求...\n")
                resp2 = client.get('/api/members/admin%40decorateme.local')
                result.write(f"狀態碼: {resp2.status_code}\n")
                result.write(f"回應: {resp2.get_json()}\n")

    except Exception as e:
        result.write(f"\n✗ 錯誤: {e}\n")
        import traceback

        result.write(traceback.format_exc())

    result.write("\n測試完成\n")

print("測試完成，請檢查 cookie_test_result.txt")
