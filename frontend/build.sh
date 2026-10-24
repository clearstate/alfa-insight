#!/usr/bin/env bash
# Резервная сборка без Vite (esbuild). Основной путь — `pnpm install && pnpm build`.
# Имена ассетов содержат хеш содержимого: браузер не покажет устаревший интерфейс после обновления.
set -euo pipefail
cd "$(dirname "$0")"
ES="${ESBUILD:-esbuild}"
rm -rf dist && mkdir -p dist/assets
"$ES" src/main.tsx --bundle --minify --format=iife --target=es2020 --jsx=automatic --define:process.env.NODE_ENV=\"production\" --outfile=dist/assets/app.js
hash() { (sha1sum "$1" 2>/dev/null || shasum "$1") | cut -c1-10; }
JS="app.$(hash dist/assets/app.js).js"; CSS="app.$(hash dist/assets/app.css).css"
mv dist/assets/app.js "dist/assets/$JS"; mv dist/assets/app.css "dist/assets/$CSS"
cp public/favicon.svg dist/favicon.svg
cat > dist/index.html <<HTML
<!doctype html>
<html lang="ru"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />
<link rel="icon" type="image/svg+xml" href="/favicon.svg" /><title>А-Бизнес — новостная аналитика</title><link rel="stylesheet" href="/assets/$CSS" /></head>
<body><div id="root"></div><script src="/assets/$JS"></script></body></html>
HTML
echo "built: $JS $CSS"
