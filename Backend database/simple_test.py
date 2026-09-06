#!/usr/bin/env python
import sys
import os

os.chdir('Backend database')
sys.path.insert(0, '.')

# 寫入測試檔案
with open('test_result.txt', 'w', encoding='utf-8') as f:
    f.write("開始測試...\n")

    try:
        from app import app

        f.write("✓ App 載入成功\n")

        import json

        f.write("✓ JSON 模組載入成功\n")

        with app.test_client() as client:
            f.write("✓ Test client 建立成功\n")

            # 測試登入
            resp = client.post('/api/login',
                               data=json.dumps({
                                   'email': 'admin@decorateme.local',
                                   'password': 'admin123'
                               }),
                               content_type='application/json')

            f.write(f"登入狀態碼: {resp.status_code}\n")
            f.write(f"登入回應: {resp.get_json()}\n")

            if resp.status_code == 200:
                f.write("✓ 登入成功\n")

                # 檢查 Cookie
                cookie = resp.headers.get('Set-Cookie')
                if cookie:
                    f.write(f"✓ Set-Cookie 已設定\n")
                else:
                    f.write("✗ 沒有 Set-Cookie\n")
            else:
                f.write("✗ 登入失敗\n")

    except Exception as e:
        f.write(f"✗ 錯誤: {e}\n")
        import traceback

        f.write(traceback.format_exc())

    f.write("\n測試完成\n")

print("測試腳本已執行完畢，請檢查 test_result.txt")
