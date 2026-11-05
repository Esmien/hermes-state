# Задачи владельца

<!-- Протокол: скилл owner-task-digest. Правь статусы здесь и отправляй событие в TG.
     Блок задачи: "## #N Заголовок", ниже строки "ключ: значение".
     status: pending | in_progress | blocked | done
     priority: high | normal | low
     progress: 0..100
     updated: YYYY-MM-DD
     note: одна строка, без переносов -->

## #1 Модульный установщик: профили core / agent / full
status: pending
priority: high
progress: 0
updated: 2026-11-05
note: план из 8 работ в vps-infra/docs/modules-plan.md (коммит 4378521); в профиле agent Hermes идёт напрямую в LiteLLM

## #2 Мультиагентный контур: три зоны доверия
status: pending
priority: normal
progress: 0
updated: 2026-11-05
note: концепт в vps-infra/docs/multiagent-tiers.md; эскалация типизированными заявками, allowlist в хуке, гостям без docker.sock
