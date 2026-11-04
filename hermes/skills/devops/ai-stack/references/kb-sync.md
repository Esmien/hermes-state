# kb-sync — git → база знаний Open WebUI

Автосинк четырёх репозиториев (`vps-infra`, `vpn-service`, `music_bot`, `hermes-state`) в базу знаний
«AI Stack (auto)» (`kb_id` в конфиге). Цель: владельцу не нужно руками скачивать архивы и заливать папку.

## Файлы

- `/usr/local/bin/kb-sync.py` — весь движок, stdlib.
- `/etc/kb-sync/config.json` — `kb_id` + список репозиториев (`name`, `url`, `branch`). Без секретов.
- `/etc/kb-sync/env` (0600) — `KB_BASE`, `KB_API_KEY` (ключ админа OWUI), `GITHUB_TOKEN`.
- `/var/lib/kb-sync/repos/<name>` — shallow-клоны; `/var/log/kb-sync.log`; `/var/lib/kb-sync/state.json`.
- `kb-sync.service` (oneshot) + `kb-sync.timer` — `OnCalendar=00/2:15`, `RandomizedDelaySec=300`.

Прогон вручную: `kb-sync.py --dry-run` (план), `kb-sync.py` (полный), `systemctl start kb-sync.service`.
`--repo X` — только для отладки и **без уборки**: синк подмножества иначе удалит остальные репозитории.

## Протокол, который использует сам UI

1. `POST /api/v1/files/?process=true&process_in_background=false` (multipart: `file`, `metadata={"file_hash": sha256}`) —
   важно `process_in_background=false`, иначе `file/add` ответит 400 (файл ещё не обработан).
2. `POST /api/v1/knowledge/{kb}/sync/diff` с манифестом `[{path, filename, checksum, size}]` —
   вернёт `added/modified/deleted/mkdir/rmdir/directory_map`. `size` обязателен (модель `FileManifestEntry`).
3. `POST /{kb}/dirs/create {name, parent_id}` — по возрастанию глубины пути.
4. `POST /{kb}/file/add {file_id, directory_id}`.
5. `POST /{kb}/sync/cleanup {file_ids, dir_ids}` — удаляет лишнее и осиротевшие каталоги.

## Грабли (каждая стоила прогона)

- **Манифест обязан быть общим для всех репозиториев.** `sync/diff` считает лишним всё, чего нет в манифесте:
  прогон по одному репозиторию удаляет файлы остальных. Поэтому collect → один diff → upload → cleanup.
- **Один контент = один файл в коллекции.** Повторная заливка тех же байт даёт
  `400 Duplicate content detected` (проверка идёт по векторам коллекции, не по БД). Поэтому манифест
  дедуплицируется по sha256, а при совпадении предпочитается путь, который уже занят в базе
  (`kb_existing_paths` через `psql`), иначе файл будет плавать между репозиториями каждый прогон.
  Побочный эффект: `vpn-service` отдаёт в базу 1 файл из 27 — остальные побайтово совпадают с `vps-infra/assets/vpn`.
- **Пустые файлы** (`__init__.py` нулевой длины) сервер отклоняет: `400` «content is empty». Пропускать на клиенте.
- Если `file/add` упал после загрузки — удалять загруженный `file_id` (`DELETE /api/v1/files/{id}`), иначе копятся сироты.
- Ошибки печатать с телом ответа: без него все 400 выглядят одинаково и диагноз стоит часа.
- `GET /api/v1/auths/api_key` возвращает существующий ключ админа — не перегенерировать (перегенерация ломает другие интеграции).

## Что не делает

- Не трогает старую ручную базу «AI Stack» (196 ссылок, из них 191 в корне) — она осталась как есть.
- Не индексирует бинарь, архивы, дампы, `.env`, ключи, `*.lock`, файлы > 768 КБ, каталоги `__pycache__`/`node_modules`/`data`.
- Не сообщает в Telegram, если изменений не было (иначе шум каждые 2 часа).
