#!/usr/bin/env bash
# Запуск Alfa Insight на macOS/Linux без Docker. Нужен Python 3.12.
set -euo pipefail
cd "$(dirname "$0")"
PY=""
for c in python3.12 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)'; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "Нужен Python 3.12"; exit 1; }
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --disable-pip-version-check -r requirements.lock.txt
echo "Откройте http://localhost:8080 (логин demo, пароль demo)"
exec .venv/bin/python -m services.insight.server
