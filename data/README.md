# data

| Каталог | Коммитится | Назначение |
|---|---|---|
| `synthetic/` | да | синтетические тестовые данные для end-to-end |
| `raw/` | нет (`.gitignore`) | исходные CSV и PDF кейса |
| `eval/` | да | размеченный оффлайн-набор: пары (клиент, событие) с ожиданиями |

## Откуда брать данные

```bash
make fetch-data   # scripts/fetch_data.sh, URL задаётся в RAW_DATA_URL (.env)
```

Если правила кейса запрещают публикацию исходных данных — они не коммитятся, а
скачиваются скриптом. Для воспроизводимости демо используйте `synthetic/`.

## Схема файлов

- `clients.csv` — `company_id,name,inn,okved,industry,region,revenue,employees,products,key_partners`
  (списки — через `;`).
- `news.csv` — `item_id,title,text,url,source_name,published_at,companies,industries,regions`.
- `analytics/*.pdf` — PDF аналитики для разбора.
- `eval/labels.jsonl` — по строке на пару `{company_id, event_id, relevant, expected_claims, notes}`.
