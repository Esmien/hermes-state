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
5. Только теперь писать sources: `deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt <codename>-pgdg main`.
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

## Что не считать причиной

- Ошибка apt на одной машине при рабочем ключе и рабочем URL — состояние той машины
  (недокачанный/нечитаемый keyring, старый `.list`), а не «репозиторий сломался».
  Код всё равно должен сам переустанавливать ключ и говорить, на каком шаге встал.
- Прогон после такой правки начинать с той же одной команды `curl … | sudo bash`: шаги
  идемпотентны, уже пройденные повторно не ломаются.
