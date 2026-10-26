# Per-model system prompts

Goal: a prompt/persona that applies **only** when one specific model is active,
leaving every other route byte-identical.

## The rule

No config field binds a prompt to a model. `agent.system_prompt` is global and
injected on every call (context tier, never cached); `display.personality` /
`/personality` is a session overlay that is equally global once selected; an
alias (`model.aliases`, `model_aliases`) carries only `model, provider,
base_url, api_key, key_env`. So when the user asks for a prompt on a separate
model, writing `agent.system_prompt` is the wrong answer even though it makes
the immediate run look right — it changes every other model's prompt and ships
twice on any gateway route that also injects one (an Open WebUI preset prepends
its `params.system` to the incoming system message: see the `ai-stack` skill,
`references/coupling-hermes.md`).

The one supported mechanism is a plugin registering a bounded system-prompt
section whose text is a **function of the session's model**.

## Plugin recipe (verified end-to-end)

```
$HERMES_HOME/plugins/<name>/
  plugin.yaml     # name, version, description, provides_hooks: []
  __init__.py     # register(ctx)
  persona.md      # the prompt text, verbatim, owned by the user
```

```python
from pathlib import Path

_SECTION_ID = "my-persona.prompt"      # lowercase, digits, '.', '_', '-'
_PREFIXES = ("muse",)                  # model-id prefixes that get the text
_PERSONA = Path(__file__).with_name("persona.md")


def _render(session_info):
    model = str(session_info.get("model") or "").lower()
    if not model.startswith(_PREFIXES):
        return ""                      # empty ⇒ section dropped, nothing added
    return _PERSONA.read_text(encoding="utf-8").strip()


def register(ctx):
    if not _PERSONA.read_text(encoding="utf-8").strip():
        return                          # inert until the owner supplies text
    ctx.register_system_prompt_section(_SECTION_ID, _render, max_chars=3900)
```

API facts that cost time to discover:

- `ctx.register_system_prompt_section(id, content, position=..., max_chars=...)`
  accepts a **string or callable**; the only valid `position` today is
  `after_memory` (i.e. near the end of the prompt, not first as a gateway
  preset would place it — the text is identical, the position is not).
- The callable receives a read-only `MappingProxyType` with `session_id`,
  `model`, `provider`, `platform`, `profile_name`, `cwd`. Filter on `model`:
  match on a prefix, because at render time the model may be the real id
  (`muse-spark-1.3-contributor`) rather than the alias name (`muse`).
- Returning `""`/whitespace/`None`, a non-str, or text over `max_chars` silently
  drops the section (warning in the log). `max_chars` is capped at **4000** and
  the aggregate across all plugin sections at 8000 — check the prompt length
  before promising to carry a long persona.
- The rendered section is **frozen per session**: `/model <alias>` mid-session
  does not re-render it. Tell the user to open a new session (`/new`).
- A newly created plugin is **`not enabled`** — `hermes plugins enable <name>`,
  which prints `takes effect on next session`. Without it the section never
  renders and every check looks like a broken matcher.
- `hermes plugins doctor <path>` validates discovery/manifest/import/register but
  reports `0 tool(s), 0 hook(s)` for a section-only plugin — that is not a
  failure, it simply does not count sections.

## Verify which prompt the model actually got

Do not infer it from the reply. The prompt is persisted per session and joined
by hash:

```sql
select model, billing_provider, system_prompt_hash from sessions order by started_at desc limit 3;
select length(prompt), prompt from system_prompts where hash='<hash>';
```

Read it with `python3 -c "import sqlite3…"` when the `sqlite3` CLI is absent.
Check the section marker (`## Plugin Context: <section-id>`) is present in the
target-model session, and run one query on an ordinary model to prove the block
is **absent** there. Pair it with `session_model_usage` (`model`,
`billing_provider`, `billing_base_url`) to prove which upstream answered.

Keep the persona in its own file (`persona.md`) and let the owner paste the text
in: replacing the file is then the whole edit, with no config or code change.
