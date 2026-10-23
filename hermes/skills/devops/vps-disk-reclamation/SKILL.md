---
name: vps-disk-reclamation
description: "Use when disk fills or user asks what eats space."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, disk, docker, containerd, snap, journald, cleanup]
---

# Disk reclamation (this VPS)

## When to Use

User asks «кто сжирает место / что можно удалить», a disk alert fires, or you need headroom before an ingest/build. Covers host-level filesystem: Docker/containerd, snap, journald, and the agent's own ~/.hermes. NOT the Open WebUI DB-ingest growth (that lives in the ai-stack skill, «Memory & disk headroom»).

## Host facts that change the answer

- Root FS is /dev/sda1, ~96 GB. **Report % used first** — a large absolute number (40 G) can still be 41% = healthy. Do not alarm before quoting the percentage.
- **Docker is backed by containerd here, so the real consumer shows up as /var/lib/containerd, not /var/lib/docker.** du on /var/lib/docker massively understates (390 M vs 23 G). The authoritative view of *reclaimable* is `docker system df` against the running daemon — use that, not du, to decide what to clean. Snapshots live under io.containerd.snapshotter.v1.overlayfs/snapshots, layers under io.containerd.content.v1.content; the daemon's namespace is moby (a `ctr -n k8s.io …` probe returns nothing — there is no k8s here).
- **/root/.hermes (tools/, cache/uv, installs/) is the agent's own runtime, not junk.** tools/ holds ffmpeg, python, node, and the agent's browser (chromium-<ver>). Never prune it as "cache".
- System **snap chromium is NOT the agent's browser.** The agent's browser is /root/.hermes/tools/chromium-* (used by agent-browser); removing the snap does not affect it, and keeping the snap does not help it. Name this distinction when the user says «удаляй хромиум, тебе же он не нужен».

## Procedure

1. **Size up.** `df -h -x tmpfs -x devtmpfs -x overlay | sort -k5 -hr | head` and `du -xhd1 / | sort -hr | head -25`. Drill with `du -xhd1 <bigdir>` then `du -xhd3 <bigdir>` (bounded depth — never unbounded du on /).
2. **Docker is usually the top consumer** — go straight to `docker system df`, then `docker image ls -a --format '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}\t{{.ID}}'`, `docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Size}}'`, `docker image ls --filter dangling=true`, `docker volume ls -qf dangling=true`.
3. **Snap old revisions.** `snap list --all | awk '/disabled/{print $1, $3}'` — each disabled line is a superseded revision and is safe to drop.
4. **journald.** `journalctl --disk-usage` (this host accumulates 330+ MB).
5. **Report the eaters, then the safe-reclaim set, then STOP for confirmation.** Format: bullet list of consumers with sizes, then "что безопасно удалить" with the exact commands and expected freed size, then the approval question. Keep it short (the user answers in one line).
6. **Apply only after the user confirms**, then verify: `df -h /` and re-run `docker system df` (expect 0B reclaimable).

### The standard safe-reclaim set

```bash
docker image rm <dangling-id>            # висячий <none> образ — usually the single biggest win
docker builder prune -f                  # build cache
docker volume rm <dangling-volumes>      # orphans only
docker image rm $(docker image ls -qf dangling=true)   # if several
snap remove <name> --revision=<rev>      # drop a superseded revision; the active one stays
snap remove --purge <name>               # drop the snap entirely (incl. /snap and /root/snap user data)
journalctl --vacuum-size=100M
```

## Pitfalls

- **Every removal here is destructive — present the plan and WAIT for «Да».** The user's standing rule: «оставляем всё, что хотя бы косвенно может навредить текущим процессам». Remove only clear orphans; anything that merely *looks* unused (a named volume, an install dir, a snap) gets named as uncertain and left until the user decides.
- **`docker volume ls -qf dangling=true` is the orphan test; a named volume is not automatically disposable.** Confirm a volume is truly unattached before naming it: `docker ps -a --format '{{.Names}}' | while read c; do echo "$c -> $(docker inspect -f '{{range .Mounts}}{{.Name}} {{end}}' \"$c\")"; done`. If a container binds a host path instead of the volume, the volume is an orphan even though its name looks official.
- **A disabled snap revision is not the snap.** `snap remove <name> --revision=<rev>` frees the old revision and leaves the active install running; `snap remove --purge <name>` removes the whole snap. Choose deliberately — the user may only want the orphan (old revision), not the app.
- **Before removing a system service/snap, confirm nothing consumes it:** `systemctl is-enabled <unit>`, `systemctl is-active <unit>`, `ps aux | grep -i <name>`, and `snap connections <name>` (a consumer shows there). No process + disabled service + no dependents = safe.
- **A build cache line in `docker system df` with 0B reclaimable after a prune is the correct end state** — do not re-prune "because it still shows 596 MB" (that is live cache).
- **Do not run unbounded du or dump the whole tree.** Depth-limit (-xhd1/-xhd3), and never cat/tail the .env files you encounter while surveying.

## Related

- Disk growth caused by Open WebUI ingest (document_chunk, needs VACUUM FULL): ai-stack skill, «Memory & disk headroom».
