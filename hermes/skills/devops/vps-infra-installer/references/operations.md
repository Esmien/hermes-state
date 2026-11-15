# Эксплуатация: синхронизация, мониторинг, бэкапы

- **Авто-коммит и пуш** (watcher на inotify + one-shot push, валидация дерева и скан на
  секреты, ловушки «no changes» и ручного `git commit`) —
  [references/installer-pitfalls.md](references/installer-pitfalls.md) → «Авто-коммит и пуш».
- **Новый хостовый скрипт/юнит — это файлы И записи в списках `install.py`.** `assets/host/bin/<name>`
  копируется в `/usr/local/bin` только если имя есть в `HOST_BIN_SCRIPTS`; юнит из
  `assets/host/systemd/` ставится только если он есть в `CORE_TIMERS` / `CORE_SERVICES` /
  `NOTIFY_SERVICES` (сам `.service` таймера подтягивается автоматически). Забыть список — тихая
  поломка: на живом хосте всё живо (файл положен руками), а после переустановки таймера нет и
  никто не замечает. Проверка перед коммитом: `python3 -m py_compile install.py` +
  `python3 install.py --dry-run`.
- **nginx-конфиг, поправленный руками на хосте, сразу копировать в `assets/host/etc/nginx/conf.d/`**
  и сверять `diff -q` — иначе recovery-репозиторий расходится с живым хостом, а по нему
  восстанавливают.
- **Beszel** (hub на `127.0.0.1:8090`, unix-сокет, PocketBase API, `TOKEN` из `fingerprints`,
  алерты только вручную), внешний контур (`uptime.yml` `*/10`, `uptime-heartbeat.timer`,
  `deadman-ping.sh`) и TLS (wildcard `*.esmien.ru` через **DNS-01 Cloudflare**,
  `/root/.secrets/cf.ini` 0600; зона `qd.je` **выведена из эксплуатации** — не возвращать в
  `legacy_hosts`, ретрай-таймеры не ставить) —
  [references/beszel-and-monitoring.md](references/beszel-and-monitoring.md).
- **Бэкап БД через бота** и `webui_data` (реестр `file_id`, части ≤18 МБ,
  `webui-data-backup.timer` Sun 04:00 UTC, `RESTORE_DBS`) — [references/migration.md](references/migration.md).
