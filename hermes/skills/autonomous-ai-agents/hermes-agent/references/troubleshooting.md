# Troubleshooting

### Voice not working
1. Check `stt.enabled: true` in config.yaml
2. Verify provider: `python -c "import pm; pm.sync_venv(['stt-whisper'], explicit=True)"` or set API key
3. In gateway: `/restart`. In CLI: exit and relaunch.

### Tool not available
1. `hermes tools` — check if toolset is enabled for your platform
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `hermes doctor` — check config and dependencies
2. `hermes auth` — re-authenticate OAuth providers (or `hermes auth add <provider>`)
3. Check `.env` has the right API key
4. **Copilot 403**: `gh auth login` tokens do NOT work for Copilot API. You must use the Copilot-specific OAuth device code flow via `hermes model` → GitHub Copilot.

### Changes not taking effect
- **Tools/skills:** `/reset` starts a new session with updated toolset
- **Config changes:** In gateway: `/restart`. In CLI: exit and relaunch.
- **Code changes:** Restart the CLI or gateway process

### web_extract shows a stale page (result caching)
`web_search`/`web_extract` cache results for 20 minutes (PR #94618) — a
repeat fetch of the same URL within the TTL is served from cache, which
can look like "my website changes aren't showing up."

Automatic carveouts (always fetched live, never cached):
- localhost / 127.0.0.1 / `*.local` / `*.localhost` / single-label LAN
  hostnames / private + link-local IP ranges (dev servers, hot-reload
  builds, chat-GUI artifact previews)
- URLs matched by `security.website_blocklist`
- failed responses and keyless-rescue-served responses

Developing a site tested over the PUBLIC internet (Vercel/Netlify
preview, ngrok/cloudflared tunnel, staging domain)? Public DNS isn't
auto-carved-out — list the host in config.yaml:

```yaml
web:
  cache_exempt_hosts:      # always fetched live; effective immediately
    - mysite.vercel.app
    - "*.ngrok-free.app"
    - mysite.dev           # suffix match: also covers preview.mysite.dev
```

Blunt instruments: `web.cache_ttl_minutes: 1` (min) or
`web.cache_enabled: false` disables both caches entirely.

### Skills not showing
1. `hermes skills list` — verify installed
2. `hermes skills config` — check platform enablement
3. Load explicitly: `hermes -s name` (or the skill's own `/<name>` slash command)

### Gateway issues
Check logs first:
```bash
grep -i "failed to send\|error" ~/.hermes/logs/gateway.log | tail -20
```

Common gateway problems:
- **Gateway dies on SSH logout**: Enable linger: `sudo loginctl enable-linger $USER`
- **Gateway dies on WSL2 close**: WSL2 requires `systemd=true` in `/etc/wsl.conf` for systemd services to work. Without it, gateway falls back to `nohup` (dies when session closes).
- **Gateway crash loop**: Reset the failed state: `systemctl --user reset-failed hermes-gateway`

### Platform-specific issues
- **Discord bot silent**: Must enable **Message Content Intent** in Bot → Privileged Gateway Intents.
- **Slack bot only works in DMs**: Must subscribe to `message.channels` event. Without it, the bot ignores public channels.
- **Windows-specific issues** (`Alt+Enter` newline, WinError 10106, UTF-8 BOM config, line endings): see `references/windows-quirks.md`.

### Auxiliary models not working
If `auxiliary` tasks (vision, compression, session_search) fail silently, the `auto` provider can't find a backend. Either set `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, or explicitly configure each auxiliary task's provider:
```bash
hermes config set auxiliary.vision.provider <your_provider>
hermes config set auxiliary.vision.model <model_name>
```

### Aux task 401 with the *provider's own* error (stale credential)
`vision_analyze` (or compression) returns something like `401 Your session has expired or the token is invalid` while the main model keeps answering normally. That is not a Hermes bug and not an outage: the aux task routed to that OpenAI-compatible provider, and the key Hermes holds for it is dead — most often because the other side re-issued its key and invalidated the old one.

1. Split the two failures before touching anything: main-model calls working + aux calls 401 = credential on the aux provider, not config.
2. Prove it in one request: `GET <base_url>/models` with `Bearer <key from .env>` — 401 confirms a stale key, 200 with a model count confirms the key.
3. Write the current key into `~/.hermes/.env` **and into every other consumer of that same credential** — the same key routinely lives in a service's own env file, and fixing only one leaves the other broken.
4. Restart the gateway: Hermes reads `.env` at process start and keeps it in memory, so the edit alone changes nothing mid-session. This is an owner action — `systemctl restart hermes-gateway` — the agent cannot restart its own gateway.

Prevention: an integration that exposes a "create key" endpoint often *regenerates* rather than returns the existing key. Read the current key from the service's own store (DB/UI) instead of minting a new one, and when you must mint, propagate it to all consumers in the same pass.

### Reading a screenshot when vision is unavailable
Text-first fallback that actually works on phone photos of a monitor: install `tesseract-ocr` + `tesseract-ocr-rus` and Pillow in a throwaway venv, then upscale 3–4x, grayscale and boost contrast (~2x) before OCR with `--psm 6`.

- Whole-frame OCR of a photographed screen returns noise. Crop into horizontal bands (top / middle / bottom), upscale each, and OCR them separately — that recovers UI labels, section headers and button text reliably.
- Say that the reading came from OCR, and that vision itself is still broken, so the user can judge how much to trust the detail.
- OCR recovers text only: it cannot tell you which element the user means by «вот этот артефакт». When the reading is ambiguous, name what you see and ask which element is meant instead of guessing.

### "Reset permissions" / auto-approving everything
See `references/security-privacy.md` — wipe the "Always allow" stores, don't touch yolo mode.

