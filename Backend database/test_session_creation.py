#!/usr/bin/env python
"""測試 Session 建立"""
import sys
import os
import json

os.chdir('Backend database')
sys.path.insert(0, '.')

with open('session_test_result.txt', 'w', encoding='utf-8') as result:
    result.write("開始測試 Session 建立...\n")
    
    try:
        from app import app, create_member_session
        from models import Members
        result.write("✓ 模組載入成功\n")
        
        with app.app_context():
            # 查詢測試會員
            member = Members.query.filter_by(email='admin@decorateme.local').first()
            if not member:
                result.write("✗ 找不到測試會員\n")
                sys.exit(1)
            
            result.write(f"✓ 找到會員: {member.email}\n")
            result.write(f"  phone_number: {member.phone_number}\n")
            
            # 嘗試建立 session
            result.write("\n嘗試建立 session...\n")
            try:
                session_token = create_member_session(member)
                result.write(f"✓ Session 建立成功\n")
                result.write(f"  Token: {session_token[:20]}...\n")
            except Exception as e:
                result.write(f"✗ Session 建立失敗: {e}\n")
                import traceback
                result.write(traceback.format_exc())
                sys.exit(1)
    
    except Exception as e:
        result.write(f"\n✗ 錯誤: {e}\n")
        import traceback
        result.write(traceback.format_exc())

print("測試完成，請檢查 session_test_result.txt")