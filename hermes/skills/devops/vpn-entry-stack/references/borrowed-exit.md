# Borrowed exit (third-party subscription)

An exit lifted from someone's paid plan is a shared credential, not a free tunnel: provider panels count **unique IPs**, not devices, so this server shows up as one more client beside the owner's phone. The owner's plan is **unlimited** — the `720 GB / ∞` on the card is traffic *spent*, not a quota — so volume is not what gets you banned; concurrency and datacenter origin are. Symptoms still worth knowing: the phone and the server knocking each other offline, or the account flagged for sharing.

A subscription bought **for the server alone** removes the duplicate-client signature (one key, one IP, exactly what the plan expects) and cuts the ban risk a lot, but not to zero: the provider still sees a datacenter origin, and transit/resale is usually forbidden in the terms. Keep a dedicated subscription off the phone and treat it as a layer under an owned VPS, not a replacement.

Two plans, two different roles — measured, not assumed (`scripts/pool_probe.py`, `scripts/inject.py`):

- **«серверная (ретрансляторы)»** carries the relay pool `p1…p19` and is **personal**: 200.0 MB injected through `p1` → +200.9 MB on its counter (0.45 % overhead). Nobody else is on that key.
- **«мобильная (глушилки)»** carries `fr` and `fi` and is **shared with strangers**: 100.0 MB through `fr` → +100.5 MB, yet the same counter took 5.6 GB in 12 minutes and 258 MB in 3 minutes while the stack pushed ≈0.3 MB in those windows and no family device was on it (their traffic shows on Estonia and the `p*` relays in the stats dashboard). Its purpose is the whitelist bypass, so it is the one path that can die for a reason that is not ours.

Both plans report `total=0` (unlimited) and `upload=0` (download only) — volume is never the constraint, so never argue limits. Standing decision: `fr`/`fi` stay, Gemini rides them only on Gemini requests (automated), and **no migration onto the relay pool is wanted** — do not propose it again.

These sellers are typically **resellers** (arbitrage): one key, but exits on unrelated ASNs (AEZA Paris, PLAY2GO Helsinki). That explains both why they are cheap and why they cannot fix IP reputation — they rent someone else's subnets. Practical consequence: the exit behind a node can change without notice, so re-run the geo checker before blaming our side when Gemini breaks.

**Лимит устройств живёт в заголовке подписки, а не на ноде.** Панель считает `x-hwid` на эндпоинте выдачи, поэтому вытащенный конфиг этот слой просто не проходит: нода видит один UUID и устройств не считает вовсе. Зато трафик по UUID она считает точно (переплата ~0.5 %), поэтому «персональный кред или пул» — измеримый вопрос, а не предмет рассуждений про оптовиков (Usage stats §3).

**Плата за план покупает не доступ, а стабильность креда.** Отзыв приходит и в подписку, и на ноды одним событием: `/france`, `/fi` и весь пул `/p<i>` умирают вместе, а `sub_expiry.py` предупреждает лишь за 3/2/1 день. Экономить здесь не на чем — бесплатный тариф называется «до следующего крона».

### Turning a plan into a pool

Panels built on Remnawave serve a decoy to clients they do not recognise: two vless nodes named `Данное приложение не обновлено` / `или не поддерживается`, both on `0.0.0.0:1`. A browser UA, `v2rayNG/…` or `ClashMeta/…` all get that decoy. What works is a supported app UA **plus** a hardware-id header:

    curl -sS -A 'v2rayTun/4.7.0' -H 'x-hwid: <any hex>' '<sub-url>' -o sub.b64

`Happ/2.11.0` with the same header returns the profile as a JSON Xray config instead. Pad before decoding (`base64 -d` wants `len % 4 == 0`), then parse one link per line.

A second decoy means a different problem: a list of nodes named `Превышен лимит устройств` / `@VPNUI_bot` / `Сбросить лимит устройств` is the panel's device-limit page, not a parsing failure — the server's IP became one client too many. Either ask the owner to reset the limit in the provider bot, or skip the subscription entirely and have him export the node link from the phone app (cheaper — a reset gets consumed again on the next refresh).

**Credentials are per plan, not per protocol.** Inside one plan every vless node shares a single UUID and every trojan node a single password, so one key opens the whole plan. Across two plans (PC vs mobile) they differ, and a node will not answer to the other plan's key: swapping the credential and retrying is the fastest way to tell "node dead" from "wrong key". `scripts/test_whitelist.py <sub> <other-sub> <indices> [--mobile]` does exactly that — builds each node with one plan's credential, then with the other's if the first run is silent.

Handing a family subscription the *mobile* plan's keys exposes that plan: one leaked link grants every node. Say so before wiring it in.

**Labels lie — probe every node.** On one 24-node plan every node carried a country flag and a friendly name, yet only 2 gave Google a supported country: the German, Swedish, Polish, US, Albanian and Austrian exits all answered `ru`. A reseller registers its whole address space the same way, so the flag describes the sale, not the geo. Run `scripts/probe_sub.py <sub-file> [indices]` — it builds an Xray client config per link, runs each one with the host binary (`/usr/local/bin/xray`; no container involved), and prints exit IP + Google country — then route only the accepted nodes.

Two node kinds are unusable here: `hysteria2` links (Xray core has no such protocol) and nodes whose page yields `com` instead of a country code (Google could not place the address — not a supported verdict). Nodes that return 0 bytes are dead; treat them as absent rather than as blocked.
