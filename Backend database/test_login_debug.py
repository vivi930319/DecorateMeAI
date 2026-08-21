#!/usr/bin/env python
"""診斷登入問題"""
import sys
import os

os.chdir('Backend database')
sys.path.insert(0, '.')

print("=" * 60)
print("登入問題診斷")
print("=" * 60)
print()

try:
    from app import app
    import json
    
    print("✓ 應用程式載入成功")
    print()
    
    with app.test_client() as client:
        # 測試 1: Health check
        print("1. 檢查伺服器狀態...")
        resp = client.get('/healthz')
        print(f"   狀態碼: {resp.status_code}")
        if resp.status_code != 200:
            print("   ✗ 伺服器未運行")
            sys.exit(1)
        print("   ✓ 伺服器正常")
        print()
        
        # 測試 2: 嘗試登入
        print("2. 測試登入 (admin@decorateme.local)...")
        login_data = {
            'email': 'admin@decorateme.local',
            'password': 'admin123'
        }
        resp = client.post('/api/login', 
            data=json.dumps(login_data),
            content_type='application/json')
        
        print(f"   狀態碼: {resp.status_code}")
        data = resp.get_json()
        print(f"   回應: {data}")
        
        if resp.status_code == 200:
            print("   ✓ 登入成功")
            
            # 檢查 Cookie
            set_cookie = resp.headers.get('Set-Cookie')
            if set_cookie:
                print(f"   ✓ Set-Cookie 已設定")
                print(f"     {set_cookie[:100]}...")
            else:
                print("   ✗ 沒有 Set-Cookie！")
            print()
            
            # 測試 3: 讀取會員資料
            print("3. 測試讀取會員資料...")
            resp2 = client.get('/api/members/admin%40decorateme.local')
            print(f"   狀態碼: {resp2.status_code}")
            data2 = resp2.get_json()
            print(f"   回應: {data2}")
            
            if resp2.status_code == 200:
                print("   ✓ 讀取會員資料成功")
            else:
                print("   ✗ 讀取會員資料失敗")
        else:
            print("   ✗ 登入失敗")
            if data and 'error' in data:
                print(f"   錯誤碼: {data['error'].get('code')}")
                print(f"   錯誤訊息: {data['error'].get('message')}")
    
    print()
    print("=" * 60)
    print("診斷完成")
    print("=" * 60)
    
except Exception as e:
    print(f"✗ 錯誤: {e}")
    import traceback
    traceback.print_exc()