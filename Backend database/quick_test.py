#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("開始測試...", flush=True)

try:
    print("1. 載入模組...", flush=True)
    from app import app, create_member_session
    from models import Members
    print("   ✓ 完成", flush=True)
    
    print("2. 建立 app context...", flush=True)
    with app.app_context():
        print("   ✓ 完成", flush=True)
        
        print("3. 查詢會員...", flush=True)
        member = Members.query.filter_by(email='admin@decorateme.local').first()
        if not member:
            print("   ✗ 找不到會員", flush=True)
            sys.exit(1)
        print(f"   ✓ 找到: {member.email}", flush=True)
        
        print("4. 建立 session...", flush=True)
        token = create_member_session(member)
        print(f"   ✓ Session 建立成功: {token[:20]}...", flush=True)
    
    print("\n所有測試通過！", flush=True)
    
except Exception as e:
    print(f"\n✗ 錯誤: {e}", flush=True)
    import traceback
    traceback.print_exc()