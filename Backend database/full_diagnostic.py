#!/usr/bin/env python
"""完整診斷登入流程"""
import sys
import os
import json

os.chdir('Backend database')
sys.path.insert(0, '.')

# 寫入日誌檔案
log_file = open('diagnostic_result.txt', 'w', encoding='utf-8')


def log(msg):
    print(msg)
    log_file.write(msg + '\n')


try:
    log("=" * 60)
    log("完整診斷登入流程")
    log("=" * 60)

    # 1. 載入 app
    log("\n【步驟 1】載入 Flask app...")
    from app import app

    log("   ✓ App 載入成功")

    # 2. 檢查路由
    log("\n【步驟 2】檢查路由...")
    with app.app_context():
        routes = {r.rule: r.endpoint for r in app.url_map.iter_rules()}

        if '/api/login' in routes:
            log(f"   ✓ /api/login -> {routes['/api/login']}")
        else:
            log("   ✗ /api/login 不存在！")

        if '/api/members/<path:email>' in routes:
            log(f"   ✓ /api/members/<path:email> -> {routes['/api/members/<path:email>']}")
        else:
            log("   ✗ /api/members/<path:email> 不存在！")

        if '/api/logout' in routes:
            log(f"   ✓ /api/logout -> {routes['/api/logout']}")
        else:
            log("   ✗ /api/logout 不存在！")

    # 3. 檢查 MemberSession 模型
    log("\n【步驟 3】檢查 MemberSession 模型...")
    from models import MemberSession, Members

    log("   ✓ MemberSession 模型已載入")

    # 4. 測試登入
    log("\n【步驟 4】測試登入...")
    with app.test_client() as client:
        login_data = {
            'email': 'admin@decorateme.local',
            'password': 'admin123'
        }

        resp = client.post('/api/login',
                           data=json.dumps(login_data),
                           content_type='application/json')

        log(f"   狀態碼: {resp.status_code}")
        response_data = resp.get_json()
        log(f"   回應: {response_data}")

        if resp.status_code == 200:
            log("   ✓ 登入成功")

            # 5. 檢查 Cookie
            log("\n【步驟 5】檢查 Set-Cookie...")
            set_cookie = resp.headers.get('Set-Cookie')
            if set_cookie:
                log(f"   ✓ Set-Cookie 已設定")
                log(f"   {set_cookie[:120]}")
            else:
                log("   ✗ 沒有 Set-Cookie！")

            # 6. 測試讀取會員資料
            log("\n【步驟 6】測試讀取會員資料...")
            resp2 = client.get('/api/members/admin%40decorateme.local')
            log(f"   狀態碼: {resp2.status_code}")
            response_data2 = resp2.get_json()
            log(f"   回應: {response_data2}")

            if resp2.status_code == 200:
                log("   ✓ 讀取會員資料成功")
            else:
                log("   ✗ 讀取會員資料失敗")
        else:
            log("   ✗ 登入失敗")
            if response_data and 'error' in response_data:
                log(f"   錯誤碼: {response_data['error'].get('code')}")
                log(f"   錯誤訊息: {response_data['error'].get('message')}")

    log("\n" + "=" * 60)
    log("診斷完成")
    log("=" * 60)

except Exception as e:
    log(f"\n✗ 錯誤: {e}")
    import traceback

    log(traceback.format_exc())

log_file.close()
