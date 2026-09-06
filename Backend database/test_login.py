#!/usr/bin/env python
"""測試登入密碼驗證"""
import sys
from app import app, db
from models import Members
from extensions import bcrypt

with app.app_context():
    print("=" * 60, flush=True)
    members = Members.query.all()
    print(f'Total members in DB: {len(members)}', flush=True)

    if not members:
        print("ERROR: No members found in database!", flush=True)
        sys.exit(1)

    for m in members[:5]:
        print(f'\n{"=" * 60}', flush=True)
        print(f'Email: {m.email}', flush=True)
        print(f'Name: {m.name}', flush=True)
        print(f'Password hash exists: {m.password_hash is not None}', flush=True)

        if m.password_hash:
            print(f'Hash length: {len(m.password_hash)}', flush=True)
            print(f'Hash (first 30 chars): {m.password_hash[:30]}', flush=True)
            print(f'Hash starts with $2b$: {m.password_hash.startswith("$2b$")}', flush=True)

            # Test password verification
            test_passwords = ['wrong', 'rtery13789', 'test123', '']
            for pwd in test_passwords:
                result = m.verify_password(pwd)
                print(f'  verify_password("{pwd}"): {result}', flush=True)
        else:
            print("ERROR: password_hash is None or empty!", flush=True)

    print(f'\n{"=" * 60}', flush=True)
    print("Test complete", flush=True)
