# Admin API over SQLite — agreed shape

The account state is spread over `users.json`, `config.json`, a `kind` file per token directory, the stats
state and the generated pages. Both shipped bugs of that split (a new profile built from the full node list,
a `/u/<token>` page outliving its account) come from mutating several of those places per operation. The
agreed direction: one service owns the state in SQLite, everything else is a rendered artifact.

## Invariants

- The DB is the single source of truth. `config.json`, the bundles and the `/u/` pages are **rendered
  artifacts** from it. The moment someone edits `config.json` by hand the picture splits again.
- One apply path, under one lock, owned by the service. Today `vpn-cfg apply` is called from `users.py`,
  the watchdog and any script — that is where half-state came from.
- `users.name` is the join key into xray (`email = "<inboundTag>:<name>"`). A rename is therefore a full
  re-render plus apply, not an `UPDATE`; either forbid renames or make them an explicit operation inside
  the apply lock and say so in the API.
- Subscription `kind` (`main` | `lte`) is a column, never a file.

## Tables

- `users`: `id`, `name` (unique, the xray key), `uuid` (secret), `title` (nullable override), `is_protected`,
  `created_at`, `updated_at`, `disabled_at` (soft delete).
- `subscriptions`: `id`, `user_id`, `kind`, `token` (secret, unique), `created_at`, `revoked_at`.
- `traffic_samples`: `id`, `user_id`, `ts`, `up_bytes`, `down_bytes`, index on `(user_id, ts)` — window
  sums become SQL instead of a JSON blob.
- `events`: `id`, `ts`, `actor`, `action`, `target`, `payload` (JSON) — audit; with several people able to
  read the panel, "who created/reissued/deleted this" is worth 20 bytes a row.

`is_protected` replaces a hardcoded name set in the API code: the owner's key cannot be deleted, only
reissued. `revoked_at` keeps a rotated token as a row, so «ссылка отозвана» is distinguishable from
«такой не было». `disabled_at` keeps a removed person's history and makes an undo possible; a hard purge
is a separate, explicit operation.

## Secrets

- Never commit the database. Live DB under `/var/lib/…`, `0600`; the repo gets an `age`/gpg-encrypted
  dump, and the key lives outside the repo and outside the service `.env`.
- SQLCipher is only worth it when the DB file itself has to travel; a key stored next to the file is
  theatre, not encryption.
- A "secret-free DB" (uuid/token in a root-only file, DB references them) reintroduces exactly the split
  we are removing — not recommended.
- API responses never carry raw `uuid`/`token`. They return ready-made links (`page`, `main`, `lte`) built
  server-side, so a dump of the API or a logged response leaks nothing usable.

## Schemas (Pydantic v2)

- `UserCreate(name)` — the same `^[A-Za-zА-Яа-яЁё0-9 _-]{2,24}$` validation as today: the name becomes a
  directory name and an xray email.
- `UserOut` — `id`, `name`, `title`, `is_protected`, `disabled_at`, `created_at`, `last_seen_at`,
  `traffic_24h_mb`, `traffic_total_mb`. No secrets, `from_attributes=True`.
- `Links` — `page`, `main`, `lte`; the only place a token leaves the service.

## Parity to keep

- Owner key: no delete, reissue only (new uuid + new tokens in one operation); old links die, new links are
  returned immediately.
- Delete costs the person their tunnel mid-apply and is not a one-click undo (today tokens are parked under
  `/var/www/esmien-sub/.disabled/`, the uuid is dropped from the config).
- Stats: xray counters reset whenever a container restarts, and every apply restarts one — store the
  container's `StartedAt` and treat a changed boot as a fresh baseline, not as a delta.
