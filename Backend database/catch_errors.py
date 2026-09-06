#!/usr/bin/env python
import sys
import os
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(BASE_DIR, 'error_log.txt')

try:
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        f.write("開始執行\n")
        f.flush()

        sys.path.insert(0, BASE_DIR)
        f.write(f"Python path: {sys.path[0]}\n")
        f.write(f"CWD: {os.getcwd()}\n")
        f.flush()

        f.write("正在載入 app...\n")
        f.flush()
        from app import app

        f.write("App 載入成功！\n")
        f.flush()

except Exception as e:
    with open(OUTPUT, 'a', encoding='utf-8') as f:
        f.write(f"\n錯誤: {e}\n")
        f.write(traceback.format_exc())
        f.flush()
    print(f"錯誤: {e}", flush=True)
    traceback.print_exc()

print("腳本執行完畢", flush=True)
