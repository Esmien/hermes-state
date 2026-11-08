# Should we build the VPN control plane ourselves?

The question arrives as «а мы не изобретаем велосипед?» while planning a backend that owns users, keys, subscriptions, traffic and the xray config. Answer it before writing a line, and answer it honestly: the CRUD-and-megabytes layer is solved software, the product layer is not.

## What already exists

- **Marzban** — closest to the stack the owner would choose anyway: FastAPI, SQLAlchemy, SQLite/MySQL, Docker, REST API, per-user subscription links, traffic accounting, node API. If his wish list were written down, it would read as Marzban's feature set.
- **3x-ui** — the popular panel: inbounds, clients, per-client limits and traffic, subscription links. Its model is inbound-centric, which is exactly the wrong axis for a product built on «one node, routing decided on the server».
- **Hiddify, Remnawave** — same family, different accents.

## What none of them do

- One visible node in the client (`meta` shape) with Google/.ru/direct decided by balancers and scenario rules on the server.
- A second profile whose only job is bypassing ISP white lists (the LTE provider-node list) — panels show node lists as the main offering, which is the opposite idea.
- Per-token branded landing pages with Happ/INCY buttons, QR and copy-link.
- Blue/green config application with probing and no dropped sessions; panels restart the core.

That product layer is ours regardless of choice below. It is also small: the whole control plane today is roughly 600 lines across `users.py`, `make_sub.py`, `make_pages.py`, `stats_collect.py`, `subgen_api.py` and `vpn-bluegreen.py`.

## What actually hurt

Not missing features — scattered state: `users.json`, `config.json`, `kind` files inside subscription dirs, `state.json`, page files, two git repos. Every real bug came from that split (profile created without its shape, page surviving a delete), not from the absence of a panel.

## Three options, with honest costs

1. **Lift Marzban and add the product layer.** Saves the users/keys/traffic/API week. Cost: someone else's data model, someone else's upgrades, and our scenario routing has to live next to it without fighting it. Choose when speed matters more than ownership.
2. **Consolidate what exists into one service.** ~2 evenings: one DB, one repo, same features. Removes the scattered-state class of bugs and nothing else. Choose when the goal is «чтобы не валялось по серверу».
3. **Write it from scratch.** ~5–7 evenings (skeleton+migration 1, config render+apply 1–2, subs/pages 1, stats 0.5–1, admin UI 1–2). Choose when the owner wants the project itself — then read Marzban's schema and API surface first so the design is not invented twice.

## Rules

- Never propose option 3 as «порядок на сервере»: order is option 2, ownership is option 3. Say which goal the recommendation serves.
- Whatever the choice, the service stays the only writer of `config.json`; a second write path brings the drift straight back.
- The parameterisation test from the spec applies to the service too: another number of inbounds and another domain must be configuration, not code.
