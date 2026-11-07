# Свой RU-выход (VLESS+Reality) вместо ресейлерских релеев

Зачем: Госуслуги/банки/маркетплейсы нужны без выключения VPN. Ресейлерские RU-узлы флапают и стоят денег — свой бокс убирает зависимость.

## Что проверять ДО включения в маршрут

1. `curl` с самого бокса напрямую: `gosuslugi.ru` (https 200, http 307), `sberbank.ru`, `tbank.ru`, `vtb.ru`, `alfabank.ru` (с браузерным UA — иначе часть отдаёт 000), `ozon.ru` 307, `wildberries.ru` 498 (антибот = норма).
2. Датацентровые IP РФ часто в блэклистах ГУ/банков — если https отдаёт 000, бокс бесполезен, менять адрес.
3. Внешний IP с бокса = адрес из панели (не NAT). Диск/сеть: `dd` на 128 МБ, `ping` от входа (Москва от Таллина ≈ 40 мс).

## Установка (без curl|bash)

- Бинарник копировать из рабочего контейнера: `docker cp vpn-router:/usr/local/bin/xray` + `scp` — версия совпадает с парком.
- Ключи Reality: `xray x25519` → `PrivateKey` (сервер) + `Password (PublicKey)` (клиент). shortId: `openssl rand -hex 8`.
- Инбаунд: port 443, `vless`, `security: reality`, `dest`/`serverNames` — реальный TLS-сайт, `sniffing` с `destOverride: [http,tls]`.
- `freedom` outbound: `domainStrategy: UseIPv4` (на боксе обычно нет IPv6 — иначе висяки на AAAA).
- ufw: `allow 22/tcp` ДО `--force enable`; 443 — только с IP входа.

## Грабли сторожа (три подряд, все дают ложный DEAD)

1. **probe через gstatic из РФ не проходит** → РФ-узлы проверять `ya.ru`, `mail.ru`, `connectivitycheck.gstatic.com`. То же для `observatory.probeUrl`: `https://cp.cloudflare.com/generate_204` работает со всех выходов.
2. **новый узел не в `observatory.subjectSelector`** → `leastPing` без данных, .ru-запросы просто висят. Добавлять тег при установке.
3. **сторож принимал только 200/204**, а `ya.ru`/`mail.ru` отдают 302 → все РФ-узлы «мертвы». Принимать любые 2xx/3xx.

Симптом «всё висит, а на боксе curl за 20 мс» = ровно эти три пункта, а не сеть.

## Ключевое

- В подписке это НЕ появляется: выход выбирает сервер, клиент видит один узел.
- `scenario_override.json` = {"bal-ru": ["ru1", "direct"]} — свой узел первым, Эстония как фоллбэк; релеи p15-p17 из сценария убрать, они флапают и дёргают `apply` каждую минуту.
- Тестовый прямой вход (клиент → бокс без Эстонии): отдельный reality-инбаунд на 8443 + ufw allow; проверять, что госуслуги 200. Временный узел в одну подписку — `extra_nodes.json` в каталоге токена (name/link/clash/sing), `make_sub.build_meta` его подхватывает; остальные токены не трогает.

## Доступ

`ssh -i /root/.ssh/id_ed25519_ru root@<ip>`; пароль вырубать в `/etc/ssh/sshd_config.d/50-cloud-init.conf` (этот файл перебивает 99-*.conf — в sshd первое значение побеждает) + `ssh_pwauth: false` в `/etc/cloud/cloud.cfg.d/`.
