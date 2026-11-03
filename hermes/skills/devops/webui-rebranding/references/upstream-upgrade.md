# Upgrading the derived Open WebUI image

A version bump is a branding risk and a database risk at once: the seds can silently stop matching, and the release usually carries migrations that make a rollback impossible without restoring a dump. Do it in this order.

## 1. Decide whether to move at all

```bash
curl -sS -H 'Accept: application/vnd.github+json' \
  'https://api.github.com/repos/open-webui/open-webui/releases?per_page=6' \
  | /usr/bin/python3 -c 'import sys,json; [print(r["tag_name"], r["published_at"]) for r in json.load(sys.stdin)]'
curl -sS -H 'Accept: application/vnd.github+json' \
  'https://api.github.com/repos/open-webui/open-webui/releases/tags/vX.Y.Z' \
  | /usr/bin/python3 -c 'import sys,json; print(json.load(sys.stdin)["body"])' > /tmp/release.md
grep -iE 'security|CVE|migration|breaking' /tmp/release.md
```

- **A `Security Advisory` line means «update soon»**, even when the CVEs are still unpublished. That is the main reason to move off a working version.
- **`Database Migrations` means one-way.** After the first start new Alembic revisions are applied; going back means restoring the dump, not pulling the old image.
- A release published hours ago is not a release with field time. Waiting 2–3 days for the `.1` patch is a legitimate answer — and the owner will usually take it. Schedule the re-check instead of nagging.

## 2. Prove the brand still applies

Run the anchor greps from SKILL.md against the **pulled** image. Every anchor must exist with the same surrounding characters:

| Anchor | File | What breaks if it moves |
|---|---|---|
| `    WEBUI_NAME += ' (Open WebUI)'` | `backend/open_webui/env.py` | build fails (grep guard) — good |
| `href="/static/apple-touch-icon.png"`, `rel="icon" … /static/favicon.png` | `build/index.html` | v2 cache-bust icons stop being referenced |
| `'src': '/static/logo.png'` | `backend/open_webui/main.py` | manifest icon reverts to the unpatched name |
| `>Open WebUI</div>` | `build/_app/immutable/nodes/*.js` | welcome landing shows the upstream brand |

Missing anchor = patch the Dockerfile first, then build. Never ship a build where a `&& grep -q` guard was relaxed to make it pass.

## 3. Build and look at it

```bash
cd /home/ai_service/ai-stack/ai/webui-branding
docker build \
  --build-arg OPENWEBUI_BASE=ghcr.io/open-webui/open-webui@sha256:<digest> \
  -t esmien/webui:X.Y.Z-test .

docker run -d --name webui-test -p 127.0.0.1:8091:8080 \
  -e WEBUI_SECRET_KEY=testonly -e WEBUI_NAME="Esmien AI" esmien/webui:X.Y.Z-test
sleep 45           # first boot downloads embedding models; health goes green after
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8091/
curl -s http://127.0.0.1:8091/static/favicon-v2.png | sha256sum   # vs out/favicon-v2.png
```

The throwaway container keeps its own SQLite volume, so it never touches the production Postgres. Screenshot `/` (landing), `/auth` (login) and the dark theme; check the eyebrow, the title and the mark. Then `docker rm -f webui-test`.

## 4. Roll out

```bash
cd /home/ai_service/ai-stack/ai && sudo -u ai_service ./backup-databases.sh
# replace ARG OPENWEBUI_BASE with the new digest
docker compose build open-webui
docker compose up -d --force-recreate open-webui
```

Then verify: health, `alembic` lines in logs for the migrations, favicon hash, `/api/config` name, one real login. Keep the previous image tagged until the next day — it is the fast rollback for image-level problems, while schema problems need the dump.
