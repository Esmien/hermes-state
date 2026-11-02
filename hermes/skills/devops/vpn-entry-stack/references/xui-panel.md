# 3x-ui admin panel behind nginx

Panel container `3xui` (image `ghcr.io/mhsanaei/3x-ui`) listens on `127.0.0.1:2053`; it is never published raw. The public path is `https://<brand-host>:8443/panel/` on the same certificate and vhost as the VPN routes.

## Publish

1. Set the base path so the panel generates its own links under it:
   ```bash
   docker exec 3xui /app/x-ui setting -webBasePath /panel/
   docker restart 3xui
   ```
2. Add it to `brand.json` like a normal route — `paths["panel"] = "/panel/"`, `upstreams["/panel/"] = 2053` — so `apply_brand.py` regenerates it into both ports and every `legacy_hosts` block.
3. `apply_brand.py` special-cases `/panel/` with a dedicated location: `Host $http_host`, `X-Forwarded-For`, `X-Forwarded-Proto $scheme`. Without the port in `Host` and without `X-Forwarded-Proto` the panel rejects every login with **403** (CSRF) even though the page loads. Do not route the panel through the generic VLESS location template.
4. `nginx -t && systemctl reload nginx`, then `curl -o /dev/null -w '%{http_code}' https://<host>:8443/panel/` → `200`.

## Rotate credentials

```bash
PW=$(openssl rand -hex 16)
docker exec 3xui /app/x-ui setting -username admin -password "$PW"
```

`-username`, `-password`, `-port`, `-webBasePath`, `-getApiToken`, `-resetTwoFactor` are the CLI surface (`/app/x-ui setting -h`). Store the result in `/root/3xui-admin-credentials` (0600: `username`, `password`, `url`) and never echo the value into chat — hand the owner `ssh root@<host> 'grep password /root/3xui-admin-credentials'`.

## Verify the login for real

The panel is CSRF-protected, so a bare `POST /panel/login` always answers 403 and proves nothing. Two requests:

```bash
curl -sS -c /tmp/c.jar https://<host>:8443/panel/ -o /tmp/p.html
TOK=$(grep -o 'name="csrf-token" content="[^"]*"' /tmp/p.html | sed 's/.*content="//;s/"//')
curl -sS -b /tmp/c.jar -c /tmp/c.jar -X POST https://<host>:8443/panel/login \
  -H "X-CSRF-Token: $TOK" -H "Origin: https://<host>:8443" -H "Referer: https://<host>:8443/panel/" \
  --data-urlencode username=admin --data-urlencode "password=$PW"
```

Success is `{"success":true,"msg":"You have successfully logged into your account."}` — a 200 with an empty body is not a login.

## Exposure notes

Publishing the panel means the internet sees it; the only gate is the panel login. Say so when reporting, and offer `limit_req` in the vhost (`limit_req_zone … zone=panel:1m rate=10r/m`) rather than silently leaving brute force wide open. The panel also serves at the backup port, since `apply_brand.py` writes both server blocks from the same upstream map.
