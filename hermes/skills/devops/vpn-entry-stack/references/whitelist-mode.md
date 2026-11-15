# Whitelist mode (RU entry)

A whitelist is enforced on the **first hop**: the client must be able to reach the address it dials. So a chain whose first hop is this Estonian server is worthless in whitelist mode — traffic dies before it ever reaches the RU entry behind it, no matter how good that entry is. Two shapes actually work:

- the client dials the RU entry **directly** (loses the brand, the subscription and the per-tunnel control; every user then sits on the provider's single key);
- our own entry lives on a **Russian VPS** (Selectel, Timeweb, Rostelecom), and the foreign exit sits behind it — brand and control survive, at the price of one more node.

A Russian hosting IP is not automatically whitelisted either: lists cover specific service ranges, not "anything in RU". Only a real shutdown proves it; before that, say plainly that the path is unverified.

Whatever shape is chosen, the whitelist node must already be **installed in the client before restrictions hit**: the subscription is served from this host, so during a shutdown nobody can fetch or update it. Hand the family its own whitelist subscription (separate token, see Subscription) while the network is open, give the backup nodes plain names, and state that switching is manual — no client detects a whitelist and fails over by itself.

Before answering «does the whitelist expose us», count our own addresses in it: the exported list should contain **zero** `@<our entry host>` entries — those links point at the provider, and the only contact with us is the subscription URL. Say that as a number («0 из 9 узлов ведут на нас»), then state the real exposure: one shared provider key across every device.

**The raw «глушилки» links are the one thing not to hand out.** In whitelist mode the client dials the provider's node directly, so every phone is a separate simultaneous IP on one key — exactly the signature that gets a one-device plan flagged and killed. Normal traffic can fan out to any number of people through our entry (the provider then sees a single server IP); the provider's own links stay on the owner's device and on this server. If several people genuinely need whitelist-mode access, that is N provider subscriptions, not one shared link — say the price before wiring anything. When the family dials the provider directly, use **two separate subscriptions**: one for the server's exit, one for the family, otherwise the duplicate-IP signature the whole split was meant to remove comes straight back. Cost-wise that is ~2× the plan price and still cheaper than a second owned node.
