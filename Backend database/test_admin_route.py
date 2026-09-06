#!/usr/bin/env python
"""Quick test to verify /admin route exists and is accessible."""
import sys
import os

# Change to the correct directory
os.chdir('Backend database')
sys.path.insert(0, '.')

print("=" * 60)
print("Testing Admin Route")
print("=" * 60)

try:
    # Import the app
    from app import app

    print("✓ App imported successfully")
    print(f"✓ Template folder: {app.template_folder}")

    # Check routes
    with app.app_context():
        routes = [r.rule for r in app.url_map.iter_rules()]
        print(f"✓ Total routes: {len(routes)}")

        if '/admin' in routes:
            print("✓ /admin route FOUND!")

            # Find the endpoint
            for r in app.url_map.iter_rules():
                if r.rule == '/admin':
                    print(f"  Endpoint: {r.endpoint}")
                    print(f"  Methods: {r.methods}")
        else:
            print("✗ /admin route NOT FOUND!")
            print("Routes containing 'admin':")
            for r in sorted(routes):
                if 'admin' in r.lower():
                    print(f"  {r}")

    print("\n" + "=" * 60)
    print("Starting test server on http://127.0.0.1:5001")
    print("Visit: http://127.0.0.1:5001/admin")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    # Start server on different port for testing
    app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)

except Exception as e:
    print(f"✗ ERROR: {e}")
    import traceback

    traceback.print_exc()
