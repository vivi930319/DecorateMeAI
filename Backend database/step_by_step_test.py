#!/usr/bin/env python
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(BASE_DIR, 'step_test.txt')

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write("開始測試\n")
    f.flush()
    
    # 步驟 1
    f.write("步驟 1: 加入 path\n")
    f.flush()
    sys.path.insert(0, BASE_DIR)
    
    # 步驟 2
    f.write("步驟 2: 載入模組\n")
    f.flush()
    try:
        from app import app
        f.write("  ✓ app 載入成功\n")
        f.flush()
    except Exception as e:
        f.write(f"  ✗ 錯誤: {e}\n")
        f.flush()
        sys.exit(1)
    
    # 步驟 3
    f.write("步驟 3: 建立 test client\n")
    f.flush()
    try:
        client = app.test_client()
        f.write("  ✓ test client 建立成功\n")
        f.flush()
    except Exception as e:
        f.write(f"  ✗ 錯誤: {e}\n")
        f.flush()
        sys.exit(1)
    
    f.write("所有步驟完成\n")
    f.flush()

print("測試完成")