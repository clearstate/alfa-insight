#!/usr/bin/env bash
# Загрузка исходных данных кейса в data/raw/. URL берётся из RAW_DATA_URL (.env).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$ROOT/data/raw"

if [[ -f "$ROOT/.env" ]]; then
  set -a; source "$ROOT/.env"; set +a
fi

if [[ -z "${RAW_DATA_URL:-}" ]]; then
  echo "RAW_DATA_URL не задан. Укажите его в .env" >&2
  exit 1
fi

mkdir -p "$TARGET/tmp"
echo "Скачиваю: $RAW_DATA_URL"
curl -fL --retry 3 -o "$TARGET/raw.zip" "$RAW_DATA_URL"
unzip -q -o "$TARGET/raw.zip" -d "$TARGET/tmp"
rm -f "$TARGET/raw.zip"
echo "Готово: $TARGET"
