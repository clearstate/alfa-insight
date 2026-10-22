# THIRD_PARTY_NOTICES — модуль news_ingest (участник 2)

Фрагмент для общего `THIRD_PARTY_NOTICES` (сводит участник 6). Точные версии — `requirements.news_ingest.lock.txt` и общий `uv.lock`.

## Библиотеки
| Компонент | Назначение | Лицензия |
|---|---|---|
| beautifulsoup4 + soupsieve | разбор HTML статей | MIT |
| lxml | безопасный разбор XML/RSS и HTML | BSD-3-Clause |
| pdfplumber, pdfminer.six, pypdfium2 | текстовый слой PDF | MIT, MIT, Apache-2.0/BSD-3 |
| pypdf | чтение PDF (зависимость) | BSD-3-Clause |
| pytesseract + Tesseract OCR (+ `tesseract-ocr-rus`) | OCR PDF без текстового слоя (резервный путь; в среде разработки не запускался с русским языком) | Apache-2.0 |
| Pillow | рендер страниц для OCR | HPND |
| poppler-utils (`pdftoppm`) | рендер страниц PDF | GPL-2.0-or-later (системный пакет, вызывается как внешняя программа) |
| PyYAML, FastAPI, Pydantic, psycopg 3, uvicorn | см. THIRD_PARTY_NOTICES.company_profile.md | MIT / BSD / LGPL-3.0 |
| unittest (stdlib) | тесты | PSF |

## Данные и источники
| Источник | Тип | Способ | Статус |
|---|---|---|---|
| Аналитические материалы Центра макроэкономических исследований Альфа-Банка (9 PDF, предоставлены организаторами кейса) | bank_analytics | файлы + транскрипция страниц в `data/bank_analytics/*.extract.json` | используется; исходные PDF не коммитятся без разрешения организаторов; материалы защищены авторским правом Альфа-Банка и используются только в рамках хакатона |
| Банк России, пресс-релизы (RSS `https://www.cbr.ru/rss/RssPress`) | regulator | RSS + страницы | **не включён**: URL не проверен в среде без сети, условия использования/robots.txt не проверены |
| Ручной импорт (URL/текст/файл жюри) | user_submitted | `POST /api/news/ingest`, `cli import-file` | используется, надёжность 0.3 |

- Словари географии `config/geo_countries.yaml`, `config/geo_regions.yaml` сгенерированы из датасета кейса «Альфа Будущее» (`df_Uid_data_hack.csv`: названия стран и регионов); сам датасет не коммитится.

## Модели и AI
- LLM внешних провайдеров модуль **не требует**: работает на правилах. Опционально (LLM_BASE_URL) — только модели из списка кейса: Gemma 4 26B A4B (классификация/извлечение). Qwen3-VL для графиков PDF предусмотрен интерфейсом, по умолчанию выключен. Эмбеддинги не используются.

## Смоделированные интеграции и данные
- Страницы-фикстуры и RSS в `tests/news_ingest` — синтетические, сгенерированы для тестов; реальные сайты в тестах не вызываются.
- Транскрипция PDF выполнена по изображениям страниц (не машинный OCR): см. `data/bank_analytics/*.extract.json` → `extraction_note`.
- Авторизация API — заглушка `X-User-ID` участника 1.
