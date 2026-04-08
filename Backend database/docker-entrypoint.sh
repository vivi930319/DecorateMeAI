#!/bin/sh
set -e

python wait_for_services.py

python - <<'PY'
from app import app
from extensions import db

with app.app_context():
    db.create_all()
PY

if [ "${AUTO_SEED_DATA:-true}" = "true" ]; then
    python seed_data.py
fi

exec gunicorn --bind 0.0.0.0:8080 app:app
