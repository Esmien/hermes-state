# Providers & Model Aliases

Set via `hermes model` (picker) or `hermes setup`. 35+ provider profiles ship as
plugins under `plugins/model-providers/`; user plugins of the same name override.
Full docs: https://hermes-agent.nousresearch.com/docs/integrations/providers

### Providers

| Provider | Auth | Key env var(s) |
|----------|------|----------------|
| openrouter | API key | `OPENROUTER_API_KEY` |
| anthropic | API key | `ANTHROPIC_API_KEY` (also `CLAUDE_CODE_OAUTH_TOKEN`) |
| nous | OAuth device code | `hermes auth add nous` (or `NOUS_API_KEY`) |
| openai-codex | OAuth | `hermes auth add openai-codex` |
| qwen-oauth | OAuth | `hermes auth add qwen-oauth` |
| minimax-oauth | OAuth | `hermes auth add minimax-oauth` |
| copilot | Token | `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` (Copilot device flow — `gh auth login` tokens do NOT work) |
| copilot-acp | External CLI | Copilot CLI on PATH or `COPILOT_CLI_PATH` |
| gemini | API key | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| xai | API key | `XAI_API_KEY` (SuperGrok OAuth also supported) |
| deepseek | API key | `DEEPSEEK_API_KEY` |
| zai (GLM) | API key | `GLM_API_KEY` / `ZAI_API_KEY` |
| minimax / minimax-cn | API key | `MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY` |
| kimi-coding / -cn | API key | `KIMI_API_KEY` / `KIMI_CN_API_KEY` |
| alibaba (+coding-plan) | API key | `DASHSCOPE_API_KEY` / `ALIBABA_CODING_PLAN_API_KEY` |
| xiaomi | API key | `XIAOMI_API_KEY` |
| huggingface | Token | `HF_TOKEN` |
| fireworks / novita / nvidia / deepinfra / gmi / arcee / stepfun / upstage / kilocode / ai-gateway / opencode-zen / opencode-go / ollama-cloud | API key | `<NAME>_API_KEY` |
| bedrock / vertex / azure-foundry | Cloud SDK / key | AWS SDK creds / Vertex ADC / `AZURE_FOUNDRY_API_KEY` |
| custom | Config | `model.base_url` + `model.api_key` in config.yaml |

Multiple credentials per provider pool and rotate automatically (`hermes auth`).
Fallback chain when the primary fails: `hermes fallback add|remove|list` —
`fallback_providers` is **one global list for every primary**. There is no
per-alias chain: "this model falls over to that model" cannot be expressed, so
say so instead of promising a model-specific backup. Order the shared chain for
the primary the user actually runs.

### User-defined model aliases

Work with `/model <name>` in CLI and every gateway platform. Resolved by
`hermes_cli/model_switch.py::resolve_alias()`; user aliases are checked BEFORE
the built-in table, so a user `sonnet`/`grok` shadows the built-in.

```yaml
# Full form
model_aliases:
  fav:
    model: claude-sonnet-4.6
    provider: anthropic
  local-qwen:
    model: qwen3.5:397b
    provider: custom
    base_url: "https://ollama.com/v1"
  theta:
    model: theta-1
    provider: custom
    base_url: "https://theta.example.com/v1"
    key_env: THETA_API_KEY        # or: api_key: "${THETA_API_KEY}"

# Short form ("provider/model"), also via CLI:
#   hermes config set model.aliases.fav openrouter/anthropic/claude-sonnet-4.6
model:
  aliases:
    fav: openrouter/anthropic/claude-sonnet-4.6
```

`/model fav` — session-scoped; add `--global` to persist as default.

An alias with its own `base_url` authenticates with its own credential
(`api_key`, which also accepts a `"${VAR}"` reference, or `key_env`). With
neither set the key is resolved from the alias HOST, never carried over from
the provider that was active before the switch.

An alias carries no prompt: a persona bound to one model is a plugin
(`ctx.register_system_prompt_section` filtered on `session_info["model"]`), not
an alias field and **not** a global `agent.system_prompt` — see
`references/per-model-system-prompts.md`.

Built-in aliases (catalog-resolved against the active provider): `sonnet`,
`opus`, `haiku`, `claude`, `gpt5`, `gpt`, `codex`, `o3`, `o4`, `gemini`,
`deepseek`, `grok`, `llama`, `qwen`, `minimax`, `nemotron`, `kimi`, `glm`,
`step`, `mimo`, `trinity`.

### Adding a provider key + alias (verified workflow)

1. **Key → `$HERMES_HOME/.env`**, under the provider's standard env var name from
the table above (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, …). Append, never
rewrite the file; check for an existing entry first
(`grep -c '^OPENROUTER_API_KEY=' .env`). Never print the value.
2. **Alias → `hermes config set model.aliases.<alias> '<provider>/<model-id>'`**.
The short form splits on the FIRST `/`, so a model id that itself contains `/`
and `:` parses correctly: `openrouter/thinkingmachines/inkling:free` → provider
`openrouter`, model `thinkingmachines/inkling:free`.
3. **No `key_env`/`api_key` needed** when the alias host is a known provider —
the key resolves from the alias host's standard env var. Reach for `key_env`
only when the credential lives under a non-standard name.

### OpenCode Zen / Go models — the alias is one line, do not hand-set the wire

`hermes_cli/models.py::opencode_model_api_mode()` derives the transport from the
model id and `agent/opencode_affinity.py` attaches `x-opencode-session` on every
request, so a model that is *not* plain chat-completions still needs no config:

| opencode-go family | api_mode |
|---|---|
| `gpt-*`, `grok-*`, `muse-spark*` | `codex_responses` (`/responses`) |
| `minimax-*`, `qwen*`, `union-alpha*` | `anthropic_messages` |
| everything else | `chat_completions` |

```bash
hermes config set model.aliases.muse opencode-go/muse-spark-1.3-contributor
```

No `base_url`, `api_mode` or `key_env`: the relay needs `x-opencode-session`
(`400 MissingSessionID` without it) and Hermes adds it because the provider
family is `opencode-go`. `/models` on that host 403s — probe a real completion.
Both `https://opencode.ai/zen/go/v1` and `https://opencode.ai/inference/go/v1`
serve the same models; the family-heal only rewrites `/zen(/go)?` paths, so an
explicit `/inference/go/v1` base_url passes through untouched.

Sanity-check the wire (the provider decides the protocol, not the docs):
`POST {base}/chat/completions` → `400 ModelProtocolUnsupported` for muse-spark,
while `POST {base}/responses` answers 200.

### "Add model X the same way Y is set up" — identify the layer first

Y may run as a direct provider alias, through a local gateway (Open WebUI /
LiteLLM), or as a gateway preset that carries its own system prompt. Those are
three different changes. Ask/verify which one the user means before building:
reading `model`/`provider`/`base_url` from `load_config()` shows a direct route,
while a localhost `base_url` (`127.0.0.1:8080`, `:4000`) means the work belongs
to the gateway, not to Hermes config. Misreading this gets "я не про
маршрутизацию через LiteLLM, я про прямое подключение" and wasted work.

### `hermes config set` rejects values that look like YAML

A multi-line value starting with `*` (markdown bold, e.g. a hand-written system
prompt) aborts with `looks like a list/mapping but is not valid YAML/undefined
alias '*'` — nothing is written. Store it as a block scalar (`agent.system_prompt:
|` + indented text, inserted into `config.yaml` between existing keys — never a
dumped/rewritten YAML file, which drops the comments) or pass a JSON-quoted
single line (`json.dumps(text)`), then re-parse the file and assert the loaded
string equals the original before moving on.

Verify end-to-end, in this order:

- **Model id exists on the provider** — `curl -s https://openrouter.ai/api/v1/models`
  and grep the id. A typo'd id otherwise fails only at request time.
- **Real run through the alias** — `hermes chat -q "Reply with exactly: OK" -m <alias>`.
- **Confirm which model/provider the session ACTUALLY used.** The `hermes chat`
  output does not say, and the session `.jsonl` may not carry it. Query the
  canonical store instead:
  `sqlite3 $HERMES_HOME/state.db "select session_id, model, billing_provider, billing_base_url from session_model_usage order by rowid desc limit 3"`.
  A silent fallback to the previously active model shows up here and nowhere else.
- **Do not unit-test alias resolution by importing `hermes_cli.model_switch` in a
  bare interpreter** — the launcher runs an isolated bundled Python (`-I`) whose
  site-packages the system interpreter does not share, so `import ruamel` fails.
  The `hermes chat -q -m <alias>` + `state.db` path is the reliable check.

### OpenRouter `:free` variants are gated to "agentic harnesses"

`:free` model ids return `403 ... only available on agentic harnesses` unless the
request carries OpenRouter app-attribution headers. Hermes always sends them
(`HTTP-Referer`, `X-Title: Hermes Agent`, `X-OpenRouter-Categories:
productivity,cli-agent`), so such a model works inside Hermes. A bare `curl`
without those headers 403s — that is NOT a bad key or a bad model id. Re-test
with the headers before concluding anything is broken.

Reasoning models can also return `content: null` with the text in
`message.reasoning` when `max_tokens` is small — raise `max_tokens` before
calling a model broken.
