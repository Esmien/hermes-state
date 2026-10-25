# Open WebUI admin auth — canonical doc lives elsewhere

**Single source of truth:** skill `credential-login-verification`, `references/open-webui-auth.md`.
It covers the auth tables, the `UI_PASSWORD` vs WebUI-password split, offline bcrypt verification,
dating a drift, and the approver fix. Read that instead; this stub exists only so the
`ai-stack` links from nearby sections land somewhere useful.

Summary: `UI_PASSWORD` in `ai/.env` is the **LiteLLM** admin password. The Open WebUI admin
password is separate and lives as `OWUI_ADMIN_PASSWORD` in `/root/.config/owui-signup-approver/env`.
