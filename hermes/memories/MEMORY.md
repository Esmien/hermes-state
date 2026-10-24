Отключение навыков в Hermes: skills.disabled — JSON-список имён (hermes config set skills.disabled '["a","b"]'; ключа нет в DEFAULT_CONFIG → ложное предупреждение CLI). Платформенно: skills.platform_disabled.<platform>. ESSENTIAL_SKILLS={hermes-agent} отключить нельзя. Читается при сборке агента → /reload-skills или /new.
§
Хост-рут этого VPS доступен напрямую как `/` — агент работает на корне хоста, НЕ в контейнере с bind-маунтом. `/mnt/host` НЕ существует; хостовые пути использовать как есть (/home/..., /etc/...). AI-стек: /home/ai_service/ai-stack (детали — skill ai-stack).
§
Telegram-боты (владелец 214062001): @esmien_vps_notificator_bot (нотификации) и @esmien_ai_backups_bot (файлы/бэкапы). Токены в /home/ai_service/notifications/.env (BOT_TOKEN, FILE_BOT_TOKEN), в чат не выводить.
§
Автозагрузка Hermes: гейтвей — systemd USER-сервис /root/.config/systemd/user/hermes-gateway.service (enabled, Linger=yes). Boot-уведомление в TG: /usr/local/bin/hermes-boot-notify.sh + hermes-boot-notify.service (oneshot, ждёт сеть→гейтвей→контейнеры из /etc/hermes-boot-expected-containers.txt, шлёт через `hermes send -t telegram`). Лог /var/log/hermes-boot-notify.log.
§
Разбор падений: docker-autorecover.timer (60с) → /usr/local/bin/docker-incident-detector.py (детект+улики в /var/lib/docker-incidents/, контейнеры не трогает) → Hermes-агент через systemd-run (docker-incident-agent.sh, отчёт в TG). Allowlist /etc/docker-autorecover.conf, лог /var/log/docker-autorecover.log, сторож docker-detector-liveness.timer. Перед ручными работами с контейнерами — touch /var/lib/docker-autorecover/pause, после снять.
§
Бэкап состояния Hermes: коммит в приватный GitHub Esmien/hermes-state ПО ФАКТУ ИЗМЕНЕНИЙ (с 24.10.2026, не по таймеру): hermes-state-watch.service (inotify, debounce 90с) → hermes-state-backup.sh (flock, GITHUB_KEY из ai-stack/ai/.env, GIT_ASKPASS) → /var/lib/hermes-state/repo. Таймер отключён. Логи /var/log/hermes-state-watch.log и -backup.log. Детали — skill hermes-state-backup.
§
Инфраструктура ставится из github.com/Esmien/vps-infra (bootstrap | bash → install.py), копия /root/vps-infra; ai-stack/deploy.sh исторический. Детали — skill vps-infra-installer.