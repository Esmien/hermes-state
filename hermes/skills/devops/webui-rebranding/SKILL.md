---
name: webui-rebranding
description: "Use when changing the Esmien AI brand assets or image."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, open-webui, branding, docker, license]
---

# Esmien AI rebranding (derived Open WebUI image)

Open WebUI runs the locally built `esmien/webui:local`, produced from `/home/ai_service/ai-stack/ai/webui-branding/`. Upstream code is not forked — the Dockerfile copies generated assets over `/app/build/static` and seds the hardcoded `" (Open WebUI)"` suffix out of `env.py`. Stack layout and upgrade procedure: `ai-stack`.

## When to Use

Any request to change the logo, favicon, splash, product name, PWA icons — or to rebuild/update/roll back the webui image. Read `ai/RESTORE_WEBUI.md` before starting; it is the authoritative rollback document.

## Build / apply

```bash
cd /home/ai_service/ai-stack/ai
sudo -u ai_service /home/ai_service/ai-stack/ai/backup-databases.sh   # absolute path; before any UI change
cd /home/ai_service/ai-stack/ai/webui-branding && <replace sources>
cd /home/ai_service/ai-stack/ai
docker compose build open-webui
docker compose up -d --force-recreate open-webui      # run backgrounded, then wait
```

`--force-recreate` is mandatory — a plain `up -d` keeps the old image layer. Then hard-refresh the browser (Ctrl/Cmd+Shift+R): the favicon is cached.

## Asset matrix — which source feeds what

| Asset | Source | Note |
|---|---|---|
| `splash.png` | colour logo | light theme |
| `splash-dark.png` | mono logo | dark theme (`isDarkMode` in `index.html`) |
| `favicon.png`, `favicon-96x96.png`, `favicon.ico`, `favicon.svg` | colour logo | one file for both themes |
| `logo.png`, `apple-touch-icon.png`, `web-app-manifest-*.png` | colour logo | PWA manifest |

`generate_assets.py` builds everything from `logo_light.png` / `logo_dark.png`; sources must be square PNG with alpha, object ≥520 px tall (largest asset is 512×512). JPEG without alpha → `python cutout.py in.jpg logo_light.png --bg light` first.

## What theming actually reaches

- **Only the splash swaps by theme.** Everything else is one file.
- **`/static/favicon.png` is the in-app brand mark, not `logo.png`** — the sidebar renders it at **22 px** in both themes; `logo.png` only feeds the generated PWA manifest.
- The manifest is generated at runtime in `backend/open_webui/main.py` from `WEBUI_NAME` with hardcoded `background_color: #343541` and the stock description; `/app/build/manifest.json` is literally `{}`. Brand colour is not wired into UI accents.
- `<title>` is stock in the raw HTML and becomes `Esmien AI` only after hydration — a FOUC, not a broken rebrand.

## Licence limit (hard constraint)

Open WebUI is BSD-3 **plus clause 4**: removing the "Open WebUI" branding is allowed only for deployments with **≤50 end users in any rolling 30 days** (4(i)), or with written permission / enterprise licence. Keep the copyright notice when distributing. Current deployment: one user — legal, but say so explicitly whenever the brand work is discussed, and never describe the UI as the owner's own code: authorship stays with the Open WebUI contributors; ours is the image, assets, config and operation.

## Legibility rule (measured, not aesthetic)

Judge every mark at the **real target size** (16–22 px), never from a 500 px export. Faceted renders and chrome/molecule art collapse there: strokes at 1 % of the mark become 0.15–0.2 px. What survives: thick orthogonal geometry (≥2 px stroke, no gaps <1 px). The crystal is fine as a splash, not as the 22 px mark.

## Verify after a rebuild

```bash
curl -s 127.0.0.1:8080/static/favicon.png | sha256sum
sha256sum /home/ai_service/ai-stack/ai/webui-branding/out/favicon.png      # must match
curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:8080/
docker inspect open-webui --format '{{.State.Health.Status}} restarts={{.RestartCount}}'
docker logs open-webui --since 5m 2>&1 | grep -iE 'alembic|migrat|error' | tail -n 10
```

Screenshot proof (login page, light/dark, sidebar at 100 %): the Playwright recipe lives in the `ai-stack` skill, Branding reference file (`branding.md`) (`~/.hermes/cache/scratch/shot/`). Take screenshots instead of describing the result — visual verdicts are what the owner judges.

## Rollback

`ai/RESTORE_WEBUI.md`: compose backup `docker-compose.yml.bak.<ts>` restores the stock image, which is pinned by digest in that document; pre-change docker state snapshot in `webui-branding/_state_snapshot/` (`compose.diff.patch`, `branding.sha256`, container/image inspect). Updating the base image = pull `:main`, read the new `RepoDigests`, replace `ARG OPENWEBUI_BASE` in the Dockerfile, rebuild.
