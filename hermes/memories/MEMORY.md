Хост-рут этого VPS = `/` (агент на корне хоста, /mnt/host нет). AI-стек /home/ai_service/ai-stack; детали и грабли — в скиллах ai-stack, vps-infra-installer, hermes-state-backup, vpn-entry-stack.
§
Правило владельца: recovery-репо (vps-infra, hermes-state) обязаны всегда совпадать с живым хостом — любое изменение на хосте сразу переносится в репо.
§
Дорогие LLM-маршруты (opus/gpt-6/sonnet) не трогать и не вызывать без явного указания; DeepSeek-flash — дефолт для тестов. Квота Sol 15–160 сообщ/5ч ОБЩАЯ для Codex CLI, OpenCode и Hermes-провайдера openai-codex — не жечь впустую.
§
Hermes ходит через Open WebUI-гейтвей (custom, http://127.0.0.1:8080/api/v1); model.aliases.* переключают сессию, дефолтный маршрут не меняют.
§
uid 1000 = ubuntu (с sudo) — и это же uid пользователя песочницы open-terminal-sandbox; файлы оттуда видны на хосте как ubuntu:ubuntu.
§
TG: 214062001 = Владислав (владелец); 917728475 = Игорь — только ssh/scp/sftp. Гейт и боты — скилл telegram-gate-and-bots.
§
Задачи владельца: доска /root/.hermes/tasks/backlog.md, бот @esmien_agent_todo_bot, дайджест Mon 08:30 МСК (systemd hermes-task-digest.timer). Протокол — скилл owner-task-digest: любое изменение статуса сразу событием в TG.
§
Браузер: lightpanda (JS, без скринов) + Chromium /root/.hermes/tools/chromium-1208/chrome-linux64/chrome (скрины); browser-тулсет в telegram.
§
ai.esmien.ru за CF-прокси (SSL strict): realip не работает, реальный IP — map $client_ip в /etc/nginx/conf.d/01-cf-client-ip.conf, лимиты/логи по нему. CF-токен /root/.secrets/cf.ini зонный.
§
Принятые риски владельца (НЕ считать недостатками): root-терминал с docker.sock (осознанно, вход только по 256-бит паролю), одна VM без кластера (бюджет, миграция ~1ч, RTO ≤1 сут), целевая атака исключена (приватный сервис), без лимитов на ключи и без алертов. Детали — скилл vps-posture-assessment.
§
Мои разборы/предложения — /root/.hermes/docs/ (в репо hermes-state как hermes/docs/). В vps-infra черновики не класть: auto-sync коммитит и пушит всё подряд.
§
Инфра-конвенция: nginx ВСЕГДА системный, в докере никогда; xray — системный бинарь; в докере только наш сервис (network_mode host, без docker.sock).