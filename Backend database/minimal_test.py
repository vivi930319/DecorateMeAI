#!/usr/bin/env python
import sys
import os

# 寫入檔案來確認執行
with open('minimal_test_output.txt', 'w', encoding='utf-8') as f:
    f.write('腳本開始執行\n')
    
    try:
        sys.path.insert(0, '.')
        f.write('1. 正在載入模組...\n')
        
        from app import app
        f.write('2. App 載入成功\n')
        
        import json
        f.write('3. JSON 模組載入成功\n')
        
        with app.test_client() as client:
            f.write('4. 建立 test client 成功\n')
            
            resp = client.post('/api/login',
                data=json.dumps({'email': 'admin@decorateme.local', 'password': 'admin123'}),
                content_type='application/json')
            
            f.write(f'5. 登入狀態碼: {resp.status_code}\n')
            f.write(f'6. 登入回應: {resp.get_json()}\n')
            f.write(f'7. Cookie: {resp.headers.get("Set-Cookie", "NONE")}\n')
            
            if resp.status_code == 200:
                f.write('8. ✓ 登入成功\n')
            else:
                f.write('8. ✗ 登入失敗\n')
    
    except Exception as e:
        f.write(f'錯誤: {e}\n')
        import traceback
        f.write(traceback.format_exc())
    
    f.write('腳本執行完畢\n')

print("腳本已執行，請檢查 minimal_test_output.txt")