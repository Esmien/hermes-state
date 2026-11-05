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
- Telegram's Bot API exposes **no topic-list method** (`getForumTopics` / `getForumTopic` / `getChatTopics` all return 404). Never plan around one; either read the `t.me/c/...` link or take the id from a real inbound message. `getUpdates` on a non-polling bot token is worth one try (forum-creation service messages may still be queued) but returns empty once the queue was consumed.
- `getChat?chat_id=<group>` **with the bot's own token** proves membership and `is_forum: true`; a bot outside the chat gets `chat not found`. Always run this before blaming Hermes routing for a bot that "is added".

## "Add this bot to that topic" — what it actually means

A topic is not a chat: a bot cannot be a member of a topic, only of the supergroup. So "add the backups bot to the Backups topic" translates to two host-side steps, not a UI action:

1. The bot must be **in the group** (members list). Check with `getChat` per token.
2. Every send must carry `message_thread_id=<thread_id>` with `chat_id=<group id>` — that is the whole routing. Nothing binds a topic to a bot, so a topic can equally well be fed by the agent, a cron job, a shell script or a notifier bot.

Consequences worth stating when the owner proposes one bot per task:

- Topics already give one agent N isolated lanes; N separate bots add nothing except N gateways and per-message `@username` routing via `exclusive_bot_mentions`. One agent bot + topics is the cheap default.
- Several bots in one group **can** be useful for provenance (alerts look like they come from the alerting bot), but each still needs its own `message_thread_id` in every send.
- Messages posted by other bots are ignored by the agent by default (`TELEGRAM_ALLOW_BOTS` off), so they never wake it as questions — safe to have notifiers post in topics.
- Shell/Python notifiers written against raw Bot API only need one extra payload field; `hermes send --to telegram:<chat_id>:<thread_id>` covers the ones already going through Hermes.

## The honest limit to state up front

Topics isolate the **conversation** only. Memory, skills, filesystem, root privileges, `state.db` and the toolset are shared across every topic — "separate task" is a separate dialogue, not a separate agent.

Real isolation (own memory, model route, own persona) = a separate profile (`$HERMES_HOME/profiles/<name>/`) with its own bot token and its own gateway. Several such bots can sit in one supergroup; `exclusive_bot_mentions` (on by default) routes by `@username`.

## Answer shape (owner-facing)

The owner asks this as a how-to, not as a request for an essay:

1. One line of verdict: what is already automatic / what actually has to change.
2. Numbered «что делать тебе» — only UI actions he performs in Telegram, 1–3 steps, imperative.
3. What I will do host-side, and the single confirmation you need from him.

Explaining the mechanism before telling him his own next step produced «Не понял ничего. Мне что делать?». If he has to act, the action list is the reply; mechanism goes below it or is dropped.

## Notifier side on this VPS

Moving the existing bots into topics is a code change, not a config flip — every sender addresses `BOT_OWNER` (DM) directly. The env-var convention, the list of senders, the task-board pointer trap and the verification commands live in the `telegram-gate-and-bots` skill; load it with this reference when the task is "route alerts into topics" rather than "how do topics work".

## Verification habit

When the question is about session routing, read the key builder, don't infer it: run `source /root/.hermes/hermes-agent/activate` then a 3-line `build_session_key` probe. The bare system `python3` lacks the install's deps (`ruamel.yaml`) and fails on import — use the install venv, not `python3` from `$PATH`.
