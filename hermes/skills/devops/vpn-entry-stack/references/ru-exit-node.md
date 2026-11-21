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
- **`scenario_override.json` — источник правды для селекторов**, он перекрывает `scenario_routes.py`. Правка `config.json` живёт меньше минуты: `vpn-scenarios.timer` переписывает балансировщики каждые 60 с, и `vpn-cfg apply` при этом рапортует успех. Порядок: override → `scenario_routes.py` (для чистого деплоя) → `systemctl start vpn-scenarios.service` → `vpn-cfg apply`.
- **Свой узел не ставить в один `leastPing`-пул с релеями.** Балансер честно берёт самый быстрый и твой может не получить ни одного запроса (замерено 3037 против 1 при 0.18 s и 0.34 s). Селектор — из одного тега, `fallbackTag` — RU-релей (`p15`), не `direct`: иначе смерть своего узла уводит `.ru` в Эстонию и ру-сервисы отвечают 403.
- **Проверять не конфиг, а распределение.** `access.log`: `accepted tcp:<host>:<port> [in-general -> <tag>]` — счётчик по тегу за окно времени. RTT по узлам: `app/observatory: the outbound <tag> is alive:<sec>` в `error.log`.
- **«Вы используете VPN» при рабочем `.ru`** — репутация ASN выхода: `p15` = `AS216246 Aeza Group`, `p17` = `AS57494 Adman` с `proxy:true, hosting:true` в базах. Проверять `curl "http://ip-api.com/json/<ip>?fields=as,hosting,proxy"`; свой ДЦ без флагов обычно снимает предупреждение, если нет — лечится только резидентским прокси.
- **Плечо сервер→сервер.** `dest` Reality платит RTT на каждом рукопожатии; проксированный CF-поддомен (свой серт снаружи, оранжевое облако) даёт настоящий TLS и не светит наши адреса. Исходящее к боксу привязывать SNAT'ом (`iptables -t nat -A POSTROUTING -d <ip> -p tcp --dport 443 -j SNAT --to-source <edge>` + oneshot-юнит): `sendThrough` на vless игнорируется, `dialerProxy` ломает дозвон.
- Тестовый прямой вход (клиент → бокс без Эстонии): отдельный reality-инбаунд на 8443 + ufw allow; проверять, что госуслуги 200. Временный узел в одну подписку — `extra_nodes.json` в каталоге токена (name/link/clash/sing), `make_sub.build_meta` его подхватывает; остальные токены не трогает.

## Доступ

`ssh -i /root/.ssh/id_ed25519_ru root@<ip>`; пароль вырубать в `/etc/ssh/sshd_config.d/50-cloud-init.conf` (этот файл перебивает 99-*.conf — в sshd первое значение побеждает) + `ssh_pwauth: false` в `/etc/cloud/cloud.cfg.d/`.
