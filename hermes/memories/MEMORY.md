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
TG: 214062001 = Владислав (владелец); 917728475 = Игорь — только ssh/scp/sftp (гейт fail_closed). Идентификация, гейт и два бота-нотификатора — скилл telegram-gate-and-bots.
