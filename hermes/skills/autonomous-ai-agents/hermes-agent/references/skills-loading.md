# How Skills Get Selected and Loaded

Answering "how does the skill system work", and debugging "why didn't the skill
fire / why is it still in context".

## Three levels

- **L0 — catalog, always in the prompt.** Only `name + description` (+ category)
  for every enabled skill: all `SKILL.md` on disk minus `skills.disabled` and
  `skills.platform_disabled.<platform>`. Roughly 3k tokens at ~75 skills; it is
  paid on every request, which is why the disabled list exists.
- **L1 — `skill_view(name)`.** Full `SKILL.md` + metadata + the *names* of
  `references/`, `templates/`, `scripts/` (never their content). The body stays in
  context for the rest of the session — hence the ~24k-char soft cap on bodies.
- **L2 — `skill_view(name, 'references/x.md')`.** One topical file, on demand.
  Reference files are free until opened. That is the whole point of the layout.

Counting: `find $HERMES_HOME/skills -name SKILL.md | wc -l` is what exists on
disk; the prompt carries only the enabled subset — a mismatch between the two is
normally `skills.disabled`, not a broken install.

## Selection

- Matching is by **description against the task**, done by the model each turn —
  there is no router or embedding index. The standing rule is to load when
  relevant or plausibly relevant; a skill also overrides generic know-how with
  this user's procedure and preferences.
- **The first ~57 characters of the description are the trigger.** "Готовит
  отчёты" never fires; "Use when a container fails or incident automation
  changes" does.
- Conditional visibility: `metadata.hermes.fallback_for_toolsets` (show only when
  those toolsets are missing), `requires_toolsets`, and the `_tools` variants.
- The user can force it: `/skill-name request`, up to 5 stacked at the start of a
  message; parsing stops at the first non-skill token, so path arguments survive.
  Skill bundles exist for combinations used repeatedly.

## Failure modes

- **Never fires** — description lacks the trigger phrasing; or the skill is in
  `skills.disabled`; or a `fallback_for_*` field hides it while the premium tool
  exists.
- **`[SKILL_PRUNED]` marker in context** — compression dropped an already-loaded
  body. Reload with `skill_view` before acting on anything that depended on it;
  ignore remaining markers for that skill afterwards.
- **Body evicted by compression but the rule still cited** — treat the rule as
  unverified until reloaded.
- **Catalog bloat** — hundreds of enabled skills dilute selection and cost tokens
  every turn. Disable rather than delete; `hermes skills opt-out` only stops
  bundled re-seeding, it deletes nothing.
- **Stale references** — the body is loaded fresh from disk, so a wrong command
  there is executed as written. Freshness is a maintenance duty, not a runtime
  guarantee.

## Writing for discovery

One-line description that starts with the trigger; procedure in the body in
order; pitfalls attached to the step they affect; long material pushed into
`references/<topic>.md` so L1 stays small. Writes go through `skill_manage`;
`skills.write_approval: true` stages every write for human review instead of
committing it.
