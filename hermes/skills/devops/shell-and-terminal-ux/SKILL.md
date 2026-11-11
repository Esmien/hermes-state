---
name: shell-and-terminal-ux
description: "Use when a server's shell/terminal should look nicer."
version: 1.0.0
author: VPS Admin
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [devops, shell, tmux, starship, terminal]
---

# Внешний вид shell и терминала

## When to Use

Владелец просит «красиво» в терминале или на сервере: промпт, tmux, тема, шрифты, — либо
спрашивает про эмулятор терминала (kitty, WezTerm, Ghostty, Alacritty).

## Две половины задачи: клиент и сервер

**Эмулятор терминала — всегда клиент.** kitty, WezTerm, Ghostty, Alacritty, Windows Terminal —
это программы для машины с экраном. На headless-хосте им негде рисовать, ставить их там нечего.
Если владелец просит kitty «на сервер» — не отговаривать от kitty и не искать ей замену:
объяснить, что она ставится на его ноутбук, а на сервере настраивается то, что видно
через эту kitty (промпт, tmux, цвета).

Проверять реальность графики, а не догадываться:

```bash
echo "DISPLAY=${DISPLAY:-} WAYLAND=${WAYLAND_DISPLAY:-}"; command -v Xorg gnome-shell
ls /usr/share/xsessions /usr/share/wayland-sessions 2>/dev/null; systemctl get-default
```

`graphical.target` по умолчанию ничего не значит: cloud-образы Ubuntu держат его с пустым
списком сессий. Признак живого десктопа — Xorg/Wayland и каталоги сессий, а не target.

## Порядок на сервере

1. Что уже есть: `command -v tmux starship; tmux -V; ls ~/.bashrc ~/.tmux.conf ~/.config/starship.toml`.
2. **starship — из GitHub releases, без `curl | sh`**: взять `tag_name` через
   `api.github.com/repos/starship/starship/releases/latest`, скачать
   `starship-x86_64-unknown-linux-musl.tar.gz`, распаковать, `install -m755 starship /usr/local/bin/`.
   musl-сборка не зависит от glibc хоста, а `install` оставляет проверяемый файл вместо
   исполненного чужого скрипта.
3. Конфиг — [templates/starship.toml](templates/starship.toml) → `~/.config/starship.toml`.
   Две строки, без Nerd Font: `╭ ╰ ❯ ⌁` есть в любом моно-шрифте, поэтому вид одинаковый
   с любого клиента. Сегменты: путь, ветка и счётчики изменений, python+venv, docker-контекст,
   время команды дольше двух секунд, красный `❯` при ошибке.
4. `.bashrc` — маркированный блок (дописывать, не перезаписывать), идемпотентно по grep
   `starship init bash`:

   ```bash
   if [ -x /usr/local/bin/starship ]; then
       eval "$(/usr/local/bin/starship init bash)"
   fi
   ```

5. tmux — [templates/tmux.conf](templates/tmux.conf) → `~/.tmux.conf`: `mouse on`, история 50 000,
   окна с 1, `|`/`-` делят панель в текущем каталоге, `set-clipboard on` (OSC 52 — копирование
   из tmux в буфер ноутбука через SSH), truecolor override, `r` перезагружает конфиг.
6. **tmux не автоаттачить из `.bashrc`.** Автостарт ломает не-tty вызовы (скрипты, агент,
   `ssh host cmd`), а выигрыш нулевой — достаточно сказать `tmux new -s main`.

## Проверка (без неё не считать сделанным)

```bash
bash -ic 'type -t starship_precmd'                      # ожидаемо: function
tmux -L probe -f ~/.tmux.conf new-session -d 'sleep 2'
tmux -L probe show -g mouse; tmux -L probe kill-server  # ожидаемо: mouse on
```

Визуальная проверка без экрана — снять содержимое панели реального PTY:

```bash
tmux -L probe new-session -d -x 100 -y 12 'cd <каталог> && bash -i'
sleep 2; tmux -L probe capture-pane -p | sed 's/\x1b\[[0-9;]*m//g'
tmux -L probe kill-server
```

Это единственный способ увидеть, что промпт действительно собран из сегментов: `starship --version`
и `starship prompt` доказывают только наличие бинаря и парсинг конфига, но не запуск в шелле.
Владельцу показывать промпт текстом (две строки, ANSI снят) — он читает с телефона, где
escape-коды не рендерятся.

## Клиентская часть

- Установка: `sudo apt install kitty` (Ubuntu/Debian), `sudo dnf install kitty` (Fedora),
  `sudo pacman -S kitty` (Arch), `brew install --cask kitty` (macOS). Windows — kitty нативно
  не поддерживается, там Windows Terminal или WezTerm.
- `kitty +kitten ssh <host>` — сам поднимает TERM/truecolor и пробрасывает буфер обмена через
  SSH; с `set -g set-clipboard on` в tmux копирование работает без настройки.
- Nerd Font проверять до правки конфига: `kitty +list-fonts | grep -i nerd`. Нет шрифта —
  не ставить иконки-глифы, иначе вместо них квадраты.

## Что теряется при переустановке

`~/.bashrc`, `~/.tmux.conf`, `~/.config/starship.toml` и сам бинарь `/usr/local/bin/starship`
в `hermes-state` **не входят** (бэкап берёт `~/.hermes` и хостовые bin/systemd, не dotfiles).
После rebuild красоту возвращать вручную; предупреждать об этом сразу, а не обещать
восстановление. Хочешь сохранить — dotfiles надо явно добавить в recovery-контур и проверить
восстановление на чистой машине.

## Откат к обычному bash

Если владелец просит «убрать рюшечки»: удалить из `~/.bashrc` весь блок от
`# ── starship prompt` до `# ── конец блока starship` (он для этого и маркирован), `cp -a` бэкап рядом.
Бинарь `/usr/local/bin/starship` и `~/.config/starship.toml` можно оставить — без `eval` они мертвы,
а удаление файлов требует подтверждения. Проверка: `bash -ic 'echo $PROMPT_COMMAND'` → пусто и
захват панели PTY показывает `root@host:~#`. Правка действует в новых шеллах, в текущем — `exec bash`.
`~/.tmux.conf` — отдельная история, промпт он не трогает: не удалять, пока не попросят.

## Грабли

- **Пакет в apt ≠ работоспособность.** `apt install kitty` на сервере проходит «успешно»,
  а запуск падает на отсутствии дисплея; ставить графические терминалы на headless-хост
  бессмысленно даже когда пакет есть в репозитории.
- **Проверка промпта в неинтерактивном bash ничего не показывает:** `eval "$(starship init bash)"`
  раскрывается только в интерактивном шелле, поэтому проверять через `bash -ic`, а не `bash -c`.
- **Сегмент python может выглядеть лишним** в каталоге с `.py`-файлами — это определение
  проекта по файлам, норма, а не ошибка конфига.
- **Пользовательские опции tmux вида `@foo` синтаксически валидны и молча игнорируются.**
  Не считать строку «настройкой»: копирование в буфер даёт `set-clipboard on`, а не
  самодельные `@`-переменные.
