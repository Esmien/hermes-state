---
name: owner-facing-docs
description: "Use when writing a .md document or report for the owner."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [documents, style, reporting, markdown, owner]
---

# Documents for the owner

## When to use

He asks for a file, not a chat answer: «напиши в .md», «собери документ», «полная инфа обо мне», «чтобы можно было показать другому», a status/overview of the server, a verdict he wants to keep. Applies to every `.md` deliverable for him, in chat or as an attachment.

This is not the same class as a chat answer. Chat: short, verdict first, bullets. Document: standalone, complete, readable top-to-bottom by someone who was not in the conversation.

## Hard style rules

- **No analogies or metaphors.** He rejected a document built on a «мастерская / станки / диспетчер» frame with «НЕ НУЖНЫ АНАЛОГИИ». Explain the thing itself, not a picture of the thing. Concrete nouns, real numbers, plain sentences.
- **«Чуть живее» means voice, not decoration.** After banning metaphors he asked for a livelier version — what he wanted was direct address to him, a judgement attached to the fact («это твой выбор, и я не считаю его недосмотром»), and short verdict lines. Do not read «живее» as literary flourishes, epithets or scene-setting.
- **A document is standalone, not a diff.** Never write it as «что изменилось», «было/стало», a changelog of the session or a list of the commands you ran. If he asks for «актуальные данные», rebuild the whole document around the current state and keep a short «что изменилось» section as one block among many, not as the skeleton.
- **Live data, never memory.** Re-query the server before writing: container states, disk and RAM, timers, registry contents, repo commit times. Memory and the previous version of the document are both stale by definition; a number copied from them will be wrong and he will notice.
- **Verdict and gaps, not a brochure.** He reads a document for the honest part: where it is weak, what is not done, what the limits are. A document with only strengths is a document he will not trust.
- **Plain language over jargon.** Explain a term on first use or drop it. «Копия вне сервера» beats «offsite replication target».
- **His conscious choices are not defects.** One server, no fallbacks, no key limits, monitoring off — state them as boundaries, never in a list of shortcomings.

## Audience

Ask or decide from the request, and say which one you wrote:

- **For him** (profile, status, «что ты обо мне знаешь») — full internal detail is fine: hosts, container names, numbers, paths.
- **«Показать другому»** — redact anything that identifies or exposes the contour: no IPs, domains, paths, container names, service names that map to his infra, no tokens (ever), no internal file names. Keep the engineering substance — what runs, what it survives, what it costs to restore. He may hand this to a colleague, a client or an employer, so assume it leaves the machine.
- **For a hiring funnel** — the document is not the artifact that gets him hired; code, tests and three written cases are. Say that plainly instead of polishing the document.

## Shape that works for a profile / status document

1. **Who he is** — age, city, stack, real level, the invented-employer history stated honestly once, what he is looking for. No praise.
2. **How he works with me** — the rules he set: verdict first, no flattery, confirm before destructive actions, his decisions are not defects.
3. **My standing rules** — priorities, secrets, destructive actions, output limits, cost limits.
4. **What I learned here** — lessons as scars («Telegram отдаёт 20 MB, поэтому части по 18»), not a technology list.
5. **The server as it is now** — live numbers, what runs, what it does by itself (per rhythm: minute / ten minutes / daily / weekly / boot).
6. **Data** — backup sets, restore proof, honest limits of the scheme.
7. **Reproducibility** — repos, installer steps, and whether restore was ever rehearsed.
8. **Scores and the one open thing** — 9/10 style per layer plus the single most important gap.
9. **What I do not know about him** — short list, invitation to fill it in.

Close with the snapshot time in UTC and a line that it does not update itself.

## Pitfalls

- **Rebuilding from the old document is how stale numbers survive.** Read the previous version only for structure; every fact comes from a fresh command.
- **A long document is fine; a padded one is not.** Depth comes from verified numbers and named limits, not from restating the same point in three sections.
- **Do not narrate the session.** «Я добавил, я поправил, я проверил» belongs in the chat reply; the document describes the system as it stands.
- **Correct your own earlier claims inside the document.** If a previous version called something a gap and it turned out to be covered, say so in a line — he notices, and silent reversal reads as sloppiness.
- **Attach, do not paste.** Write the file and send `MEDIA:/abs/path.md`; a 20 KB document pasted into chat is unreadable on a phone.
- **New file when the old one should stay.** If he asks to «собрать новый», write a new path instead of overwriting; overwriting a file this session never read is refused by the writer anyway.
