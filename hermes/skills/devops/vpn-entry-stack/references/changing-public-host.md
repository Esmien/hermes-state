# Changing the public host

Never hand-edit the nginx confs — they are generated:

1. edit `host` + `cert_dir` in `/root/vpn-router/brand.json`
2. `python3 /root/vpn-router/apply_brand.py`
3. `nginx -t && systemctl reload nginx`

`apply_brand.py` no longer emits a compat block: the `legacy_hosts` map and the `vpn-compat.conf` generation were deleted once the old free-domain vhosts and their certificates were removed for good. Keep it that way — a compat stub pointing at an old name keeps answering on the default server with a certificate mismatch and looks like a live site without being one. Legacy hosts are only worth keeping while their DNS still exists; a dead zone revives nothing.

Prerequisites before pointing the entry at a new name:

- The DNS record must exist and resolve from at least two public resolvers **before** certbot runs; HTTP-01 is issued through the port-80 ACME vhost, so a name that does not resolve yet wastes a validation attempt.
- Under Cloudflare the record is **A → server IP with proxy OFF (grey cloud)**. The orange proxy terminates TLS at the edge, so our own certificate and the per-path WebSocket routing stop matching; Cloudflare does support 8443 if proxying is ever wanted deliberately, but that is a different setup, not a checkbox. The concrete symptom of getting this wrong while issuing: HTTP-01 through an orange record answers `530` and certbot reports `unauthorized` — fix the colour, do not chase the webroot.
- A brand-new registered domain has its own Let's Encrypt bucket, so moving the entry to it sidesteps an exhausted bucket on the old name (see Certificates).

Verification after the switch, in one pass: `openssl s_client -servername <new host>` shows the new CN; `https://<host>:8443/` returns `200` and `/<path>` returns `400` (a WS inbound refusing a plain GET — that is the healthy answer); `/sub/<token>` returns `200` with the new host inside the links; a locally dialled Xray client gets a real egress IP; `check-host.net/check-tcp` on the entry port answers from most nodes. Verify the old name is *gone*, not stubbed: an unknown SNI falls through to the default server and answers `200` with the `*.esmien.ru` certificate, which reads like a working site in a log grep.

A name change has to reach the **applications**, not just nginx and the subscription. Grep every config on the host for the old name (`grep -rn '<old-host>' /root/deploy /home/ai_service --include='*.env*' --include='*.yml'`) — a webhook base URL, an OAuth redirect or an app's own public URL keeps answering `200` on the new vhost while quietly pointing at the dead one. Then re-register the webhook and confirm the provider's own state (`getWebhookInfo` → `pending_update_count=0`); the music bot sat deaf for days on an old `bot.<old-host>` URL that no TLS or HTTP check would ever flag.
