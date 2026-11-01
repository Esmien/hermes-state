# Beszel и внешний мониторинг

## Beszel

Hub+agent в Docker, `/home/ai_service/beszel`, hub на `127.0.0.1:8090`, связь через `beszel_socket/beszel.sock`. Его можно настроить через PocketBase API: superuser, затем `users`/`systems`/`fingerprints`/`user_settings`/`alerts`. Не выводи учётные данные.

- `KEY` — публичный ключ хаба (`ssh-keygen -y` от его приватного ключа); приватный ключ никогда не выводи.
- `TOKEN` — UUID коллекции `fingerprints`. Без fingerprints агент получает 401.
- Notifications задаются в `user_settings.settings` через shoutrrr webhook. Проверку выполняй `POST /api/beszel/test-notification` токеном пользователя, не суперпользователя; не выводи URL с токеном.
- Alerts создаются явно: Status, CPU, Memory, Disk. Без них графики есть, тревог нет.

## Внешний мониторинг

`.github/workflows/uptime.yml` в `vps-infra` раз в 10 минут проверяет HTTPS сервисы с GitHub Actions, после трёх неудач уведомляет Telegram. `workflow_dispatch` с `extra_url=https://httpbin.org/status/500` — реальный тест сообщения. Секреты GitHub передаются через sealed box и не выводятся.

GitHub отключает scheduled workflows в публичном репозитории после 60 дней без активности. `uptime-heartbeat.timer` ежемесячно меняет `maintainer/uptime-heartbeat.txt`, watcher коммитит. Дополнительный контур healthchecks.io: `deadman-ping.sh` и таймер, ping-URL хранится в `/etc/deadman-ping.url` и не выводится; регистрация требует email magic link.

Зона `qd.je`: лимит Let's Encrypt для registered domain общий между пользователями; certbot.timer повторяет выпуск, самописный таймер повторов не добавлять без решения владельца. Для другого ACME CA нужен отдельный выбор.
