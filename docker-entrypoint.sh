#!/bin/sh
set -eu

if [ -n "${DATABASE_URL:-}" ]; then
  echo "Waiting for database..."
  python - <<'PY'
import os
import sys
import time
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
engine = create_engine(url, pool_pre_ping=True)
for attempt in range(30):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        sys.exit(0)
    except Exception as exc:
        if attempt == 29:
            print(f"Database not ready after 30 attempts: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY
fi

echo "Running database migrations..."
clipyyy db upgrade

exec "$@"

