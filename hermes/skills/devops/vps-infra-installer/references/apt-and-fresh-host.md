# Пакеты и apt на чистой машине

Use when `install.py` ставит системные пакеты, добавляет сторонний apt-репозиторий или
падает на шаге `packages`/`postgres` при прогоне на свежей Ubuntu.

## Зонды «а не установлено ли уже»

Установщик на каждом шаге сначала спрашивает систему, есть ли уже нужное. На живой машине
это безопасно, на чистой — смертельно, если ответ «нет» реализован исключением.

- `run(cmd, check=False)` при `FileNotFoundError` обязан вернуть `CompletedProcess(rc=127)`,
  а не звать `die()`. Иначе первый же зонд отсутствующего бинарника (`psql --version` на
  чистой машине) убивает прогон ещё до установки — и в логе видно только «команда не
  найдена», без подсказки, что это проверка.
- Перед зондом необязательного бинарника — `shutil.which(name)`; нет бинарника → сразу
  `need = True`, без вызова.
- `check=True` оставлять для команд, без которых шаг действительно не имеет смысла: там
  падение — правильный сигнал.

Проверка правки без переустановки:

```bash
python3 -c "import sys; sys.path.insert(0,'/root/vps-infra'); import install; \
  a=install.build_parser().parse_args(['--only','verify']); i=install.Installer(a); \
  print(i.run(['no-such-binary-xyz'], check=False).returncode)"
# 127 — и установщик жив; check=True на той же команде должен бросить InstallError
```

## Сторонний репозиторий: ключ в бинарном keyring

`deb [signed-by=/path/key.asc]` с armored-ключом, скачанным с сайта вендора, apt читает не
всегда: файл на месте, а `apt-get update` отвечает `NO_PUBKEY …` и «repository is not
signed» — то есть ключ фактически не применён. Надёжный порядок (на примере pgdg):

1. Скачать ключ с ретраями: `curl -fsSL --retry 3 -o /usr/share/keyrings/pgdg.asc <url>`.
2. Проверить, что это ключ: размер ≥ 500 Б и в начале `BEGIN PGP PUBLIC KEY BLOCK`.
   Прокси и заглушки отдают HTML с кодом 200 — такой файл ставить нельзя.
3. `gpg --batch --yes --dearmor --output /usr/share/keyrings/pgdg.gpg pgdg.asc`, затем
   `chmod 0644`. Без `gpg` — копия как есть (fallback для урезанных образов).
4. Сверить отпечаток: `gpg --show-keys --with-colons <keyring>` должен содержать ожидаемый
   (`ACCC4CF8` для pgdg). Не совпал — `die()` с отпечатком в тексте, а не молчаливый apt.
5. Только теперь писать sources: `deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt <codename>-pgdg main`.
   Целостность держит GPG-подпись `InRelease` и хэши пакетов, поэтому http допустим и
   работает там, где https-плечо отдаёт битый кэш (но сам по себе CDN не обходит — см. ниже).
6. `apt-get update -qq`; при `NO_PUBKEY`/`not signed` — переустановить ключ и повторить
   **один** раз, второй провал — `die()` с последней строкой вывода apt (в лог — хвост).

`-qq` не глушит `W:`/`E:` — эти строки и есть диагностика, их надо ловить в `stderr` и
класть в лог, иначе установка «упала с кодом 100» без причины.

## Как проверить apt-путь, не поднимая сервер

Дешёвая проверка именно этого класса ошибок — чистый контейнер с той же Ubuntu:

```bash
docker run --rm -v /root/vps-infra:/opt/vps-infra ubuntu:24.04 bash -lc '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq python3 curl gnupg lsb-release ca-certificates
  cd /opt/vps-infra && python3 - <<"PY"
import sys; sys.path.insert(0, "/opt/vps-infra"); import install
inst = install.Installer(install.build_parser().parse_args(["--only", "postgres"]))
inst.apt_install = lambda pkgs: None      # пакеты не тянем, проверяем ключ и sources
try:
    inst.step_postgres()
except Exception as e:                    # в контейнере нет systemd — это ожидаемый конец
    print("стоп на:", e)
PY
  apt-cache policy postgresql-17 | head -3'
```

Норма: `ключ pgdg проверен и установлен`, `apt-get update` без `W:`, и `apt-cache policy`
показывает кандидата вида `17.x-1.pgdg24.04+…`. Остановка на `systemctl` — не баг
установщика: в контейнере нет systemd, шаги после установки пакетов там не проверяются.

## apt-get update — одна точка с самопочинкой

Повторный прогон на машине, где уже падал предыдущий, оставляет в
`/etc/apt/sources.list.d/` созданный установщиком `.list` от старой схемы ключа. Пока этот
файл там лежит, **любой** `apt-get update` в системе отдаёт rc=100 — включая вызов из шага
`packages`, то есть установка умирает на первом шаге, где нужен apt, и выглядит как «apt
сломался».

- Держать один метод `apt_update()`, через который идут все вызовы (в том числе `apt_install`),
  и лечить состояние внутри него: `NO_PUBKEY`/`not signed` → если нет `gpg`/`curl`, сначала
  временно закомментировать свой источник (бэкап рядом), обновиться без него, поставить
  `gnupg`, затем переустановить ключ, переписать `.list` на бинарный keyring и повторить
  update.
- Кодовое имя дистрибутива брать из `/etc/os-release` (`VERSION_CODENAME`): `lsb_release`
  есть не всегда, и `die("команда не найдена: lsb_release")` прилетает уже после успешной
  починки ключа, маскируя настоящую причину.
- После падения повторный запуск установщика — норма: шаги идемпотентны, лечить надо
  состояние машины, а не просить владельца чистить `/etc/apt` руками.

## Рассинхрон зеркала и fake-IP

`E: Failed to fetch … File has unexpected size (932154 != 932239). Mirror sync in progress?`
— это не подпись и не ключ, а несовпадение индекса с `Release`.

- Ретраить с backoff (5/15/30 c), а на последней попытке добавлять
  `-o Acquire::http::No-Cache=true -o Acquire::http::Pipeline-Depth=0`, чтобы обойти
  промежуточный кэш. Классифицировать как временные: `unexpected size`, `mirror sync`,
  `hash sum mismatch`, `failed to fetch`, `some index files failed`, `502`, `503`.
- **`No-Cache` не лечит зависший CDN.** Fastly на `Cache-Control: no-cache` отвечает тем же
  `X-Cache: HIT, HIT` с прежним `Age`, а `http` и `https` идут через один и тот же кэш
  (`Server: nginx` + `Age:` в ответе). Смена схемы URL — не обход CDN: проверять по
  заголовкам, а не по виду ссылки.
- **Диагностика «кто отдаёт старое» — сравнить `Last-Modified` по anycast-адресам:**

  ```bash
  for ip in 151.101.2.52 151.101.66.52 151.101.130.52 151.101.131.52 151.101.195.52; do
    echo -n "$ip → "
    curl -sSI --resolve apt.postgresql.org:443:$ip \
      https://apt.postgresql.org/pub/repos/apt/dists/noble-pgdg/InRelease \
    | grep -i last-modified | tr -d '\r'
  done
  ```

  Разные даты по разным адресам = завис объект на конкретном плече; одинаково свежие =
  CDN чист, ищи причину на клиенте.
- **Смотреть тело, а не заголовок.** `curl -sI` отдаёт `Last-Modified`/`Age` объекта, а apt
  читает содержимое: у зависшего плеча заголовок бывает свежим, а внутри `InRelease` —
  `Date` двухдневной давности. Проверка, которая не обманывает:
  `curl -s <url>/InRelease | grep -m1 '^Date:'` — сравнивать эту дату между плечами и с
  `Release file created at:` из вывода apt.
- **Свежий `InRelease` на всех плечах, а apt всё равно ждёт другой размер — виноват
  локальный кэш индексов.** В `/var/lib/apt/lists/` остаётся прежний `InRelease`; apt считает
  свою копию актуальной и не перекачивает её, а `Packages.bz2` тянет новый — отсюда вечный
  `unexpected size` при любых ретраях и любом IP. Лечение: удалить только свои файлы
  (`rm -f /var/lib/apt/lists/*pgdg*`) и повторить update. Установщик делает это сам в ветке
  `unexpected size` (`_purge_pgdg_lists()`), не трогая индексы других репозиториев.
- **Корня `lists/` мало — чистить и `lists/partial/`.** Недокачанный индекс лежит там как
  `Packages.bz2.FAILED`, и apt при следующем запуске докачивает его Range-запросом: старые
  байты склеиваются с новыми, размер не сходится ни с одним `Release`, и `unexpected size`
  повторяется даже после `rm -f /var/lib/apt/lists/*pgdg*`. Удалять `lists/*pgdg*` **и**
  `lists/partial/*pgdg*`. Проверить гипотезу, ничего не удаляя, — прогон с отдельным
  каталогом списков:

  ```bash
  apt-get -o Dir::State::Lists=/var/tmp/alists -o Acquire::http::Pipeline-Depth=0 update
  ```

  Прошло чисто = виновато локальное состояние (кэш/partial), а не зеркало.
- Прежде чем винить репозиторий, сверить зеркало с другой машины: скачать
  `dists/<codename>-pgdg/Release` и `main/binary-amd64/Packages.bz2`, сравнить `sha256sum`
  файла с записью в `Release`. Совпало — зеркало цело, проблема на стороне клиента.
- **Адрес из `198.18.0.0/15` в тексте ошибки apt** (`[IP: 198.18.0.184 443]`) — это fake-IP
  TUN-клиента (Clash, Hiddify, sing-box) на хосте, а не адрес PostgreSQL. Через такой прокси
  apt получает старый `Release` из кэша вместе со свежим `Packages`, поэтому ретраи не
  помогают никогда. Диагностика: `getent ahostsv4 apt.postgresql.org` в ВМ против реального
  адреса CDN, снятого с другой машины.
- **Владельцу туннель нужен для Telegram — не предлагать «выключи VPN» как единственный
  выход.** Рабочие варианты: прогон drill на машине вне туннеля, либо исключения в клиенте
  (`DIRECT` + `fake-ip-filter` для `postgresql.org`, `ubuntu.com`, `docker.com`), чтобы apt
  шёл напрямую, а Telegram — через прокси. Установщик при этом сам предупреждает, если DNS
  резолвит pgdg в fake-IP.

## Что не считать причиной

- Ошибка apt на одной машине при рабочем ключе и рабочем URL — состояние той машины
  (недокачанный/нечитаемый keyring, старый `.list`), а не «репозиторий сломался».
  Код всё равно должен сам переустанавливать ключ и говорить, на каком шаге встал.
- Прогон после такой правки начинать с той же одной команды `curl … | sudo bash`: шаги
  идемпотентны, уже пройденные повторно не ломаются.
