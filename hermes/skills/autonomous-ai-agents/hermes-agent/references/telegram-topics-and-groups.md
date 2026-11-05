# Telegram supergroup with forum topics (one task per topic)

Reference for «как собрать тебя в супергруппу с темами, каждая тема — отдельная задача».

## What is already automatic — say this first

A forum topic in a supergroup is **already its own session**, with no config and no activation:

- Session key: `agent:<ns>:telegram:group:<chat_id>:<thread_id>` — verified by executing `build_session_key` on a synthetic `SessionSource` (`thread_id` is the last key segment).
- The General topic arrives as thread `1` (or without `message_thread_id`); it is still a distinct lane from the numbered topics.
- Sessions in a topic are **shared by all members** by default: `group_sessions_per_user` does not apply inside a thread. `thread_sessions_per_user: true` is the knob that splits a topic per member. For "topic = task" sharing is what you want, so leave it alone.
- `/new` inside a topic resets only that topic.

`/topic` and BotFather **Threads Settings** are for *Private Chat Topics* in a DM (Bot API threaded DM mode). Do not propose them for a supergroup — they are a different feature and only confuse the answer. Supergroups need no `/topic`.

## Telegram-side prerequisites (owner does these manually)

Hermes cannot create a group via the Bot API, and cannot answer messages Telegram never delivers:

1. Create the supergroup, enable **Topics**, add the bot.
2. Make the bot **group admin**, or BotFather → Bot Settings → Group Privacy → **off**. Admin is the cheaper path — it avoids the global privacy toggle.
3. After changing privacy, **remove and re-add the bot**. Telegram caches delivery behaviour at join time; an existing membership keeps the old behaviour.

Symptom of a missed step: the bot works in DM, stays silent in topics.

## Authorization gates

- Sender ids in `TELEGRAM_ALLOWED_USERS` cover **every** chat type, including groups and forums. A sender not in that list is dropped even in an allowed group.
- Chat-scoped gate: `platforms.telegram.allowed_chats: ["-100…"]` (config) or `TELEGRAM_GROUP_ALLOWED_CHATS` (env). Set it so the bot never answers outside that one group.
- Negative chat ids belong in the **chat** allowlist, never in the user allowlist.
- `guest_mode: true` allows @mentions from non-allowlisted groups; leave it off for an owner-only group.

## Mention behaviour

- `platforms.telegram.require_mention` has **no default**, so an unset key means open-group behaviour: the bot answers every message it receives. For a solo owner group this is the desired mode — write in the topic, no `@` needed. Set `true` only when other people chat there too.
- `extra.ignored_threads: [12, "31"]` keeps the bot silent in specific topics.
- `observe_unmentioned_group_messages: true` (+ `allowed_chats` and `group_allowed_chats` pointing at the same group) appends unmentioned chatter as context without dispatching.

## Per-topic behaviour

- **Prompt per topic:** `platforms.telegram.extra.channel_prompts` keyed by **thread_id**, falling back to the group chat_id (topics inherit the group prompt). The adapter calls `resolve_channel_prompt(extra, thread_id or chat_id, chat_id)` — so `"5": "<vps persona>"` beats `"-100…": "<generic>"`.
- **Skill per topic:** `extra.channel_skill_bindings: [{id: "<thread_id>", skills: ["vps-posture-assessment"]}]`, or the fuller `extra.group_topics: [{chat_id: -100…, topics: [{name: VPS, thread_id: 5, skill: …}]}]`.
- **Cron into a topic:** `TELEGRAM_CRON_THREAD_ID=<thread_id>` (overrides `TELEGRAM_HOME_CHANNEL_THREAD_ID` for cron only), or target `"telegram:<chat_id>:<thread_id>"` in the job. Replies in that topic continue the topic's session.
- `/sethome` typed inside a topic makes that topic the home channel for scheduled output.

## Finding the ids

- `thread_id` is the trailing number of `https://t.me/c/<group_internal_id>/<thread_id>`; the chat id is `-100<group_internal_id>`.
- Cheapest live method: ask the owner to post in the topic and read `inbound message: platform=telegram … chat=<id> thread=<id>` from `~/.hermes/logs/gateway.log` with a bounded grep.
- Telegram ids live in `.env` — grep key names only, never print values of that file.

## The honest limit to state up front

Topics isolate the **conversation** only. Memory, skills, filesystem, root privileges, `state.db` and the toolset are shared across every topic — "separate task" is a separate dialogue, not a separate agent.

Real isolation (own memory, model route, own persona) = a separate profile (`$HERMES_HOME/profiles/<name>/`) with its own bot token and its own gateway. Several such bots can sit in one supergroup; `exclusive_bot_mentions` (on by default) routes by `@username`.

## Verification habit

When the question is about session routing, read the key builder, don't infer it: run `source /root/.hermes/hermes-agent/activate` then a 3-line `build_session_key` probe. The bare system `python3` lacks the install's deps (`ruamel.yaml`) and fails on import — use the install venv, not `python3` from `$PATH`.
