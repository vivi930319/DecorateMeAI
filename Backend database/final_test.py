#!/usr/bin/env python
"""最終完整測試"""
import sys
import os
import json

os.chdir('Backend database')
sys.path.insert(0, '.')

with open('final_test_result.txt', 'w', encoding='utf-8') as f:
    try:
        f.write("=" * 60 + "\n")
        f.write("最終完整測試\n")
        f.write("=" * 60 + "\n\n")

        # 步驟 1: 載入 app
        f.write("【步驟 1】載入 Flask app...\n")
        from app import app

        f.write("   ✓ App 載入成功\n\n")

        # 步驟 2: 檢查路由
        f.write("【步驟 2】檢查路由...\n")
        with app.app_context():
            routes = {r.rule: r.endpoint for r in app.url_map.iter_rules()}
            if '/api/login' in routes:
                f.write(f"   ✓ /api/login -> {routes['/api/login']}\n")
            else:
                f.write("   ✗ /api/login 不存在！\n")
                sys.exit(1)
        f.write("\n")

        # 步驟 3: 測試登入
        f.write("【步驟 3】測試登入...\n")
        with app.test_client() as client:
            login_data = {
                'email': 'admin@decorateme.local',
                'password': 'admin123'
            }

            resp = client.post('/api/login',
                               data=json.dumps(login_data),
                               content_type='application/json')

            f.write(f"   狀態碼: {resp.status_code}\n")
            response_data = resp.get_json()
            f.write(f"   回應: {response_data}\n")

            if resp.status_code == 200:
                f.write("   ✓ 登入成功\n\n")

                # 步驟 4: 檢查 Cookie
                f.write("【步驟 4】檢查 Set-Cookie...\n")
                set_cookie = resp.headers.get('Set-Cookie')
                if set_cookie:
                    f.write(f"   ✓ Set-Cookie 已設定\n")
                    f.write(f"   {set_cookie[:150]}\n\n")
                else:
                    f.write("   ✗ 沒有 Set-Cookie！\n\n")
                    f.write("   所有 Headers:\n")
                    for key, value in resp.headers:
                        f.write(f"     {key}: {value}\n")

                # 步驟 5: 測試讀取會員資料
                f.write("\n【步驟 5】測試讀取會員資料...\n")
                resp2 = client.get('/api/members/admin%40decorateme.local')
                f.write(f"   狀態碼: {resp2.status_code}\n")
                response_data2 = resp2.get_json()
                f.write(f"   回應: {response_data2}\n")

                if resp2.status_code == 200:
                    f.write("   ✓ 讀取會員資料成功\n")
                else:
                    f.write("   ✗ 讀取會員資料失敗\n")
            else:
                f.write("   ✗ 登入失敗\n")
                if response_data and 'error' in response_data:
                    f.write(f"   錯誤碼: {response_data['error'].get('code')}\n")
                    f.write(f"   錯誤訊息: {response_data['error'].get('message')}\n")

        f.write("\n" + "=" * 60 + "\n")
        f.write("測試完成\n")
        f.write("=" * 60 + "\n")

    except Exception as e:
        f.write(f"\n✗ 錯誤: {e}\n")
        import traceback

        f.write(traceback.format_exc())

print("測試完成，請檢查 final_test_result.txt")
