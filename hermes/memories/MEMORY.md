Отключение навыков: skills.disabled (JSON-список), skills.platform_disabled.<platform>; hermes-agent не отключается; нужен /reload-skills.
§
Хост-рут этого VPS доступен напрямую как `/` — агент работает на корне хоста, НЕ в контейнере с bind-маунтом. `/mnt/host` НЕ существует; хостовые пути использовать как есть (/home/..., /etc/...). AI-стек: /home/ai_service/ai-stack (детали — skill ai-stack).
§
Telegram-боты (владелец 214062001): @esmien_vps_notificator_bot (нотификации) и @esmien_ai_backups_bot (файлы/бэкапы). Токены в /home/ai_service/notifications/.env (BOT_TOKEN, FILE_BOT_TOKEN), в чат не выводить.
§
Автозагрузка Hermes: user-сервис /root/.config/systemd/user/hermes-gateway.service (enabled, Linger). Boot-уведомление: hermes-boot-notify.sh + .service (ждёт сеть→гейтвей→контейнеры из /etc/hermes-boot-expected-containers.txt, шлёт hermes send). Лог /var/log/hermes-boot-notify.log.
§
Разбор падений: docker-autorecover.timer (60с) → /usr/local/bin/docker-incident-detector.py (детект+улики в /var/lib/docker-incidents/, контейнеры не трогает) → Hermes-агент через systemd-run (docker-incident-agent.sh, отчёт в TG). Allowlist /etc/docker-autorecover.conf, лог /var/log/docker-autorecover.log, сторож docker-detector-liveness.timer. Перед ручными работами с контейнерами — touch /var/lib/docker-autorecover/pause, после снять.
§
Бэкап Hermes: коммит в приватный GitHub Esmien/hermes-state ПО ФАКТУ ИЗМЕНЕНИЙ: hermes-state-watch.service (inotify, debounce 90с) → hermes-state-backup.sh (flock, GIT_ASKPASS) → /var/lib/hermes-state/repo. Логи /var/log/hermes-state-*.log. Детали — skill hermes-state-backup.
§
Инфраструктура ставится из github.com/Esmien/vps-infra (bootstrap | bash → install.py), копия /root/vps-infra; ai-stack/deploy.sh исторический. Детали — skill vps-infra-installer.
§
Дорогие LLM-маршруты (opus/gpt-6/sonnet) не трогать и не вызывать без явного указания владельца; DeepSeek-flash — дефолт для тестов.
§
TG: 214062001 = Владислав (владелец, всё); 917728475 = Игорь (только ssh/conn, гейт agent-hooks/ssh-only-gate.py, fail_closed).
§
Сессии Игоря (917728475): только ssh. Не раскрывать ему инфраструктуру, пути, сервисы, инструменты, владельца.