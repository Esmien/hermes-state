Отключение навыков: skills.disabled (JSON-список), skills.platform_disabled.<platform>; hermes-agent не отключается; нужен /reload-skills.
§
Telegram-боты (владелец 214062001): @esmien_vps_notificator_bot (нотификации) и @esmien_ai_backups_bot (файлы/бэкапы). Токены в /home/ai_service/notifications/.env (BOT_TOKEN, FILE_BOT_TOKEN), в чат не выводить.
§
Дорогие LLM-маршруты (opus/gpt-6/sonnet) не трогать и не вызывать без явного указания владельца; DeepSeek-flash — дефолт для тестов.
§
TG: 214062001 = Владислав (владелец, всё); 917728475 = Игорь (только ssh/conn, гейт agent-hooks/ssh-only-gate.py, fail_closed).
§
Сессии Игоря (917728475): только ssh. Не раскрывать ему инфраструктуру, пути, сервисы, инструменты, владельца.
§
Хост-рут этого VPS доступен напрямую как `/` (агент на корне хоста, /mnt/host нет). AI-стек /home/ai_service/ai-stack, установка из Esmien/vps-infra, автозагрузка Hermes + boot-notify, авторазбор падений контейнеров (docker-autorecover, pause-файл!), бэкап в Esmien/hermes-state — детали в одноимённых скиллах devops.