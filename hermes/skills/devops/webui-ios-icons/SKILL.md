---
name: webui-ios-icons
description: Use when a WebUI home-screen icon won't refresh.
version: 1.0.0
author: Vlad (owner) + Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [devops, open-webui, ios, pwa, icons, caching]
    category: devops
    related_skills: [webui-rebranding, ai-stack]
---

# WebUI Home-Screen Icons Skill

Every icon-related surprise on a phone is a caching question, not a branding question. The server can be serving perfectly correct files while the home screen still shows last month's artwork. This skill covers what actually controls those icons on iOS and Android, and how to roll out a new logo without forcing a relative through a logout. It does **not** cover the asset build itself — that is `webui-rebranding`.

## When to Use

Load this when a logo/favicon/splash change has been applied but a phone still shows the old icon, when deciding whether it is worth changing the icon at all, or when asked why an iPhone icon changes colour with the system theme. Also load before promising anyone "it will update by itself".

## Prerequisites

None for the phone side. Server-side rollout assumes the `ai` compose project on this host (`/home/ai_service/ai-stack/ai`) and the derived image described in `webui-rebranding`.

## Quick Reference

| Surface | Who caches it | Updates on its own? |
|---|---|---|
| Browser tab favicon (desktop) | Browser favicon cache | Yes — hard refresh, then cache expiry |
| iPhone home screen (Web Clip) | iOS, per-clip | No reliable path; remove + re-add |
| iPhone home screen (bookmark) | Safari | Same as Safari site data |
| Android PWA (WebAPK) | Chrome / launcher | Only if the icon **URL** changed |
| Desktop installed PWA | App shell | Often reinstall only |

Rule of thumb: the build rebuilds what the **server** serves. Nothing in `docker compose` reaches the **phone's** cache.

## Procedure

### 1. Decide whether to touch the icon at all

Changing a home-screen icon on iOS means the clip must be deleted and re-added, and a Web Clip keeps its **own storage, separate from Safari** — deleting it drops the session cookie. On Open WebUI that is a fresh login for whoever owns the phone. So before doing branding work, answer honestly: is a new picture worth a relative logging in again? If not, stop here and keep the current icon.

### 2. Serve the new assets

Follow `webui-rebranding`: replace `logo_light.png` / `logo_dark.png`, then `docker compose build open-webui` and `docker compose up -d --force-recreate open-webui`. Fixed filenames (`apple-touch-icon.png`, `favicon.png`, `web-app-manifest-*.png`) mean content changes while the URL stays identical — which is exactly why caches hold on.

### 3. Desktop and browser tabs

Hard refresh (`Ctrl+Shift+R`). If the tab icon still sticks, clear the browser's favicon cache — that cache is separate from normal page cache.

### 4. iPhone

There is **no supported API to refresh an already-installed Web Clip icon**; Apple documents icon selection only at "Add to Home Screen" time. Options, worst to least disruptive:

- **Remove and re-add the clip** — reliable, costs a login.
- **Change the icon URL** (`apple-touch-icon-v2.png` plus matching manifest entries) — sometimes iOS refetches on next launch; undocumented, no guarantee.
- **Re-add as a bookmark instead of a web app** — in iOS 26 the Add to Home Screen sheet has an "Open as Web App" toggle; switching it off produces a bookmark whose removal does not touch Safari cookies, so the login survives. Cost: it opens with Safari chrome instead of standalone.
- **Mind the theme, not the file** — on iOS 18+ the system generates dark/tinted icon variants itself, by maths on foreground/background colours (no ML, handled by IconServices). That is why icons flip instantly when the theme changes, and it says nothing about whether new artwork has landed.

Do **not** send anyone through "clear Safari cache" — it is an extra step that fixes nothing here.

### 5. Android

Chrome only updates an installed web app's icon when the icon **URL** changes; a changed file at the same URL is treated as immutable. Icons are also security-sensitive manifest fields, so Chrome may ask the user to approve an app update. Practically: bump the filename, or reinstall.

## Pitfalls

- **Mistaking system tint for fresh artwork.** iOS 18 dark-mode icon generation is cosmetic and instant; the underlying image never changed.
- **Assuming a rebuild propagates.** The container restart is server-side only.
- **Deleting the clip "just to refresh"** on a phone whose owner does not know the password. Verify the credential or have it saved in iCloud Keychain first.
- **Versioning the URL but forgetting the manifest**, so `apple-touch-icon.png` and `web-app-manifest-*.png` disagree.
- **Promising automatic updates.** No browser documents one for installed web apps on iOS.
- **Editing `/app/backend/open_webui/static` in a live container.** `config.py` re-copies from `/app/build/static` on every start and wipes it — see `webui-rebranding`.

## Verification

Server side (proves the files are correct):

```bash
curl -s 127.0.0.1:8080/static/apple-touch-icon.png | sha256sum
sha256sum /home/ai_service/ai-stack/ai/webui-branding/out/apple-touch-icon.png   # must match
docker inspect open-webui --format '{{.Config.Image}} {{.State.StartedAt}}'
```

Device side: the only honest check is a fresh add — remove the clip, re-add, confirm the icon and then confirm the login state. Report the true state per device; do not claim a phone updated without seeing it.
