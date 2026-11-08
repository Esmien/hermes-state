# Login failure triage: what 400 / 401 / 403 actually mean

Семантика кодов и форм логина по сервисам; сюда же — гигиена секретов и ложные
следы «credential мёртв».


## A `403` on `POST /login` is CSRF, not a wrong password

- **A `403` on `POST /login` is CSRF, not a wrong password.** Go panels (3x-ui 3.x, and most cookie-session UIs) embed `<meta name="csrf-token" content="…">` in the login page and require that value in an `X-CSRF-Token` header alongside the session cookie. Fetch the page first, extract the token, then post — a bare post answers 403 with an empty body however correct the password is. Behind a proxy the same 403 appears when the panel's origin check sees a mismatched host: pass `Host $http_host` (port included) and `X-Forwarded-Proto $scheme` from nginx, because `Host $host` drops the port while the browser's `Origin` keeps it. The 3x-ui case, with rotation and a working verification sequence, is written up in the `vpn-entry-stack` skill (its `xui-panel` reference).


## A `401` is not proof the password is wrong

- **A `401` is not proof the password is wrong.** Wrong endpoint, wrong body schema, or a dead legacy route all return `401`. Establish the endpoint from logs first.


## `login: None` with a token is a success

- **`login: None` in a JSON response is not a failed login** if `token` is present — v2 changed the shape. Check the raw body before concluding.


## The owner pasted a live key: it is already burned

- **When the owner pastes a config or log containing a live key, that key is already burned.** Do not echo it back in the reply, the diff or a rewritten file — refer to it as «твой ключ» and edit around it. Finish with two concrete actions: revoke/rotate it in the issuing UI, and move it out of the config into env or the client's auth store. Config files travel into backups and git; a key in one is a key in every copy.


## basic auth in front of an API is not a fix

- **`basic auth` in front of an API is not a fix.** OpenAI-style clients send `Authorization: Bearer`, not HTTP Basic; and ACME renewal (`authenticator = nginx`) breaks unless `/.well-known/acme-challenge/` stays open. Basic auth only on `/ui/` + `/login`, with the ACME location untouched, is the shape that works.


## A secret pasted into chat (especially a group thread) is burned

- **A secret pasted into chat — especially a group thread — is burned, and the owner needs to hear it in one line.** Do not echo the value back and do not paste it into a diff or a rewritten file; use it from env/`argv` in a throwaway script, print only counts and prefixes, then delete the script. Close with the two concrete follow-ups: change the human password in the UI once logged in, and rotate whatever else came with it (a master key pasted alongside is a bearer credential readable by every member of the thread). Rotating a master key touches every client that holds it — name the dependants before promising it.
