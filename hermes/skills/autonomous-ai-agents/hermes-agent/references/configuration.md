# Configuration, Toolsets & Voice

Edit with `hermes config edit` or `hermes config set section.key value`.
Full reference: https://hermes-agent.nousresearch.com/docs/user-guide/configuration

### Config Sections (most-used keys)

| Section | Key options |
|---------|-------------|
| `model` | `default`, `provider`, `base_url`, `api_key`, `context_length`, `aliases` |
| `agent` | `max_turns` (90), `tool_use_enforcement`, `service_tier`, `verify_on_stop` |
| `terminal` | `backend` (local/docker/ssh/modal/daytona/singularity), `cwd`, `timeout` (180) |
| `compression` | `enabled`, `threshold` (0.50), `target_ratio` (0.20) |
| `display` | `skin`, `interface` (cli/tui), `language`, `show_reasoning`, `show_cost`, `pet` |
| `approvals` | `mode` (smart/manual/off), `timeout`, `cron_mode` |
| `stt` | `enabled`, `provider` (local/groq/openai/mistral/elevenlabs/deepinfra) |
| `tts` | `provider` (edge/elevenlabs/openai/minimax/mistral/neutts/gemini/piper/kittentts/deepinfra/xai) |
| `memory` | `memory_enabled`, `user_profile_enabled`, `provider`, `write_approval` |
| `security` | `redact_secrets`, `website_blocklist` |
| `delegation` | `model`, `provider`, `max_concurrent_children`, `max_iterations` (50), `max_spawn_depth` |
| `checkpoints` | `enabled`, `max_snapshots` (50) |
| `curator` | `enabled`, `consolidate` (false, opt-in aux-model consolidation), `interval_hours`, `stale_after_days` |

`hermes config check` reports sections missing from an older config.

**Always pass the FULL dotted path — a bare key name writes an inert top-level key.** `hermes config set reasoning_effort medium` answers «✓ Set» and then only *warns* («not a recognized config key — it was saved anyway»); the real key is `agent.reasoning_effort`, so the value is never read. Same for `skills.disabled`, which is also absent from the CLI's known-keys table (that warning is a false positive there, but the key is real). Check the surrounding section before setting: `grep -n "^section:" config.yaml` and `hermes config get <section.key>`, then confirm the value landed under the block (`grep -n "^  reasoning_effort:"`) and remove a stray top-level key with `hermes config unset <key>`. Read back what the agent itself will load rather than trusting the CLI echo. `agent.reasoning_effort` is consumed from the agent object (`agent/reasoning_params.py`), i.e. at agent init — a running gateway session keeps its old level until `/new`.

### Toolsets

Enable/disable via `hermes tools` (interactive) or `hermes tools enable/disable NAME [--platform P]`.
Full enumeration: `TOOLSETS` dict in `toolsets.py` (`_HERMES_CORE_TOOLS` is the default bundle most platforms inherit).

**Toolset state is PER PLATFORM** — it lives in `platform_toolsets.<platform>` in `config.yaml` (a list of toolset names, or a preset like `hermes-cli` / `hermes-telegram`). Read and write it through the CLI:

```
hermes tools list --platform telegram             # live matrix: ✓ enabled / ✗ disabled
hermes tools enable vision --platform telegram    # add to that platform's list
hermes tools disable image_gen --platform cli
```

- **`--platform` defaults to `cli`.** A bare `hermes tools enable vision` changes ONLY the CLI. When the user is talking to you from Telegram/Discord/Slack/WhatsApp, pass their platform as well — otherwise their next message still runs the old tool list.
- `hermes tools enable` is additive but rewrites the whole `platform_toolsets` block. Back up first (`cp -a $HERMES_HOME/config.yaml $HERMES_HOME/config.yaml.bak-$(date +%Y%m%d-%H%M%S)`) and diff the block after the edit to prove nothing else moved.
- Enable exactly what was asked: `vision` (image analysis), `image_gen`, `video`, `video_gen` are four separate toolsets. "Recognition, not generation" = `vision` only — and say in the reply that the siblings are still disabled.

| Toolset | What it provides |
|---------|-----------------|
| `web` / `search` | Web search + extraction / search-only subset |
| `browser` | Browser automation (Browserbase, Camofox, or local Chromium) |
| `terminal` | Shell commands and process management |
| `file` | File read/write/search/patch |
| `code_execution` | Sandboxed Python execution |
| `coding` | Code-editing helpers (LSP-backed) |
| `computer_use` | Desktop GUI control (cua-driver) |
| `vision` | Image analysis |
| `image_gen` | Image generation and image-to-image editing |
| `video` / `video_gen` | Video analysis / video generation |
| `x_search` | X (Twitter) search (X OAuth or API key) |
| `tts` | Text-to-speech |
| `skills` | Skill browsing and management |
| `memory` | Persistent cross-session memory |
| `session_search` | Search past conversations |
| `context_engine` | Pluggable context-engine hooks |
| `project` | Named multi-folder workspace tools |
| `delegation` | Subagent task delegation |
| `cronjob` | Scheduled task management |
| `clarify` | Ask user clarifying questions |
| `todo` | In-session task planning |
| `kanban` | Multi-agent work-queue tools (gated to workers) |
| `debugging` | Extra introspection tools (off by default) |
| `safe` | Minimal low-risk toolset for locked-down sessions |
| `discord`, `discord_admin`, `feishu_doc`, `feishu_drive`, `yuanbao` | Service integrations (gated on their credentials). `homeassistant` (`ha_*` tools) and `spotify` (`spotify_*` tools) are not built in: they come from the `homeassistant` / `spotify` catalog plugins (`hermes plugins install <name>`) |

Tool changes take effect at agent build: `/new` or `/reset` in-session (`/reload-skills` for skills), `/restart` for the gateway — never mid-conversation, to preserve prompt caching. Until the rebuild the new tool is simply absent from the running session's tool list — do not retry calling it; finish by the closest available route and give the user the ONE rebuild step they need.

**Verify a toolset by real execution, never by the config echo.** Run a fresh one-shot session that must use the tool and quote what the tool returned:

```
hermes chat -q "Вызови инструмент vision_analyze для локального файла /path/img.jpg с промптом 'Опиши изображение в 2 предложениях на русском'. Затем приведи ровно то, что вернул инструмент."
```

A `{"success": true, ...}` payload proves config + credentials + aux model path in one shot. Prefer this over hand-importing Hermes tool modules in the runtime venv: the venv `python3` is wrapped by the launcher shim (`-I` + `runpy`, HERMES_HOME pinning), and a hand-built import chain can die with a bogus `ModuleNotFoundError` for a package that IS installed — the one-shot session goes through the real bootstrap. (Direct imports of `agent.skill_utils` / `tools.transcription_tools` as shown elsewhere in this file do work; when one fails, switch to the one-shot instead of debugging the shim.)

**Images are described to you even with the `vision` toolset disabled.** Gateway attachments (Telegram photos, dropped files) get an analysis injected automatically. So "I can read the screenshot" is NOT evidence that `vision_analyze` exists — check `hermes tools list --platform <p>` before claiming the tool is available or missing.

`vision_analyze` runs on the **auxiliary vision model** (`auxiliary.vision.provider`, default `auto` = OpenRouter → Nous Portal → main endpoint). On a self-hosted box with no OpenRouter/Nous credential and `model.base_url` pointing at a local OpenAI-compatible server, vision rides the MAIN endpoint — fine if that model is multimodal, and the one-shot check above is what settles it. Dense phone screenshots that come back as "unreadable" need `vision.embed_target_bytes` raised (default 262144).

### Skills — enable/disable and enumeration

Skills live under `$HERMES_HOME/skills/`. Enable/disable them from config, NOT by moving or deleting files:

```
hermes config set skills.disabled '["airtable","notion","opencode"]'  # global disable list (skill load_names)
hermes config set skills.disabled '[]'                                  # re-enable everything
```

- Keys: `skills.disabled` (global list) and `skills.platform_disabled.<platform>` (per-platform; a globally disabled skill stays disabled everywhere). Readers: `hermes_cli/skills_config.py` and `agent.skill_utils.get_disabled_skill_names`.
- The CLI prints `'skills.disabled' is not a recognized config key — saved anyway`. **False positive**: the key is absent from `DEFAULT_CONFIG` but the readers above do read it. The write is correct; ignore the warning (do not "fix" it).
- `ESSENTIAL_SKILLS` (`hermes-agent`) can never be disabled — it is silently dropped from any list.
- Use the skill `load_name` (usually its directory name under `skills/`), not the display title.
- Values may be given as a YAML/JSON literal (`'["a","b"]'`) or a bare single name; `skills.disabled` is a scalar-as-one-item list slot.
- Takes effect at agent build: `/reload-skills` or `/new` in-session; `/restart` for the gateway.
- Interactive: `hermes skills` (per-category toggles); in-session `/skills`.

Verify against the live runtime rather than trusting the config echo — call Hermes' own code with its **runtime venv** (the system python lacks `ruamel`/`yaml`, so `import agent.skill_utils` fails there):

```
PY=$(ls -d $HERMES_HOME/installs/*/environments/*/venv/bin/python3 | head -1)
$PY -c "import sys; sys.path.insert(0,'$HERMES_HOME/hermes-agent'); \
from agent.skill_utils import get_disabled_skill_names; from tools.skills_tool import _find_all_skills; \
print(len(get_disabled_skill_names()))"
```

## Voice

### STT (Voice → Text)

Voice messages from messaging platforms are auto-transcribed.

```yaml
stt:
  enabled: true
  provider: local   # local (faster-whisper, free) | groq | openai | mistral | elevenlabs | deepinfra
  local:
    model: base     # tiny, base, small, medium, large-v3, turbo
```

Auto-detect priority: local faster-whisper → Groq (`GROQ_API_KEY`, free tier) → OpenAI (`VOICE_TOOLS_OPENAI_KEY`) → Mistral Voxtral (`MISTRAL_API_KEY`) → xAI → ElevenLabs.

Enabling local STT on a box with no STT provider (the common "voice notes silently do nothing" case):

1. Install the engine into the Hermes runtime venv (NOT system python — it lacks ruamel):
   `V=$(ls -d $HERMES_HOME/installs/*/environments/*/venv/bin/python3 | head -1); $V -c "import sys; sys.path.insert(0,'$HERMES_HOME/hermes-agent'); import pm; pm.sync_venv(['stt-whisper'], explicit=True)"`
   This writes a NEW `environments/<hash>/venv` and updates `installs/*/facts.json` (`packages.venv.extras` gains `stt-whisper`). No restart of the installer needed.
2. Config: `hermes config set stt.provider local`, `hermes config set stt.language ""` (auto-detect — a non-empty value like `en` forces that language and mangles other languages into transliteration), `hermes config set stt.local.model small` (base is weak for non-English; small ~500MB downloads on first use).
3. `stt.enabled` is already true by default; `stt.echo_transcripts` (default true) echoes the raw transcript back to the user. Gateway reads `stt.enabled`/`stt.echo_transcripts` (flat or nested) into `GatewayConfig.stt_enabled`.
4. The change only lands on a FRESH process: run `hermes gateway restart` (systemd user unit `hermes-gateway.service`; graceful drain via SIGUSR1) and start a new CLI session. `hermes gateway status` shows the unit and new PID.

Verify end-to-end against the live runtime (runtime venv has faster-whisper, system python does not):
   `$V -c "import sys; sys.path.insert(0,'$HERMES_HOME/hermes-agent'); from tools.transcription_tools import transcribe_audio; print(transcribe_audio('/path/clip.wav', None, 'test'))"`
   Expect `{"success": true, "provider": "local", "transcript": "..."}`. To confirm a fresh process picks it up, replicate the launch bootstrap: `python3 -I -c "import os,sys; os.environ.pop('PYTHONPATH',None); sys.path.insert(0,'$HERMES_HOME/hermes-agent'); sys._hermes_pin_default_home=True; import hermes_bootstrap, faster_whisper; print(faster_whisper.__version__)"`.

### TTS (Text → Voice)

| Provider | Env var | Free? |
|----------|---------|-------|
| Edge TTS (default) | None | Yes |
| ElevenLabs | `ELEVENLABS_API_KEY` | Free tier |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | Paid |
| MiniMax | `MINIMAX_API_KEY` | Paid |
| Mistral | `MISTRAL_API_KEY` | Paid |
| Gemini | `GOOGLE_API_KEY` | Free tier |
| NeuTTS / Piper / KittenTTS (local) | None | Free |

Voice commands: `/voice on` (voice-to-voice), `/voice tts` (always voice), `/voice off`.
