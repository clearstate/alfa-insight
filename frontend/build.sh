#!/usr/bin/env bash
# Резервная сборка без Vite (esbuild): используется, когда нет доступа к npm-реестру. Основной путь — `pnpm install && pnpm build`.
set -euo pipefail
cd "$(dirname "$0")"
ES="${ESBUILD:-esbuild}"
rm -rf dist && mkdir -p dist/assets
"$ES" src/main.tsx --bundle --minify --format=iife --target=es2020 --jsx=automatic --define:process.env.NODE_ENV=\"production\" --outfile=dist/assets/app.js
cp public/favicon.svg dist/favicon.svg
cat > dist/index.html <<'HTML'
<!doctype html>
<html lang="ru"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />
<link rel="icon" type="image/svg+xml" href="/favicon.svg" /><title>А-Бизнес — новостная аналитика</title><link rel="stylesheet" href="/assets/app.css" /></head>
<body><div id="root"></div><script src="/assets/app.js"></script></body></html>
HTML
