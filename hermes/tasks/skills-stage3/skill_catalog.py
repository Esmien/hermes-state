"""Read-only personal-skill catalogue prototype; not connected to Open WebUI.

Caller must supply an already-authorized directory descriptor. This module does
not authenticate a user and must not be exposed directly as a user tool.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


class CatalogError(Exception):
    """Fail closed on malformed content or unsafe filesystem state."""


@dataclass(frozen=True)
class Entry:
    name: str
    trigger: str
    result: str
    path: str


NAME = re.compile(r"[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?\Z")
FIELD = re.compile(r"- \*\*([^*\n]+):\*\* (\S.*)\Z")
STEP = re.compile(r"  ([1-9][0-9]*)\. (\S.*)\Z")
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
TARGET = re.compile(r"\bшаг(?:у|а|ом|е)?\s+(\d+)\b", re.IGNORECASE)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _fail(path: str, message: str) -> None:
    raise CatalogError(f"{path}: {message}")


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _trusted(info: os.stat_result, path: str, directory: bool) -> None:
    kind_ok = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not kind_ok or info.st_uid != 0 or info.st_mode & 0o022 or (not directory and info.st_nlink != 1):
        _fail(path, "небезопасный владелец, права или тип")


def _directory(parent: int, name: str) -> int:
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    try:
        _trusted(os.fstat(fd), name, True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _file(parent: int, name: str, path: str) -> str:
    fd = os.open(name, FILE_FLAGS, dir_fd=parent)
    try:
        before = os.fstat(fd)
        _trusted(before, path, False)
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False, newline="") as stream:
            text = stream.read()
        after = os.fstat(fd)
        linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _fingerprint(before) != _fingerprint(after) or _fingerprint(after) != _fingerprint(linked):
            _fail(path, "файл изменён при чтении")
        return text
    finally:
        os.close(fd)


def _validate_steps(lines: list[str], path: str) -> None:
    if not lines or lines[0] != "- **Шаги:**":
        _fail(path, "нет блока шагов")
    lines = lines[1:]
    pos, count = 0, 0
    transitions: list[int] = []
    while pos < len(lines):
        if not lines[pos]:
            pos += 1
            continue
        match = STEP.fullmatch(lines[pos])
        if not match or int(match[1]) != count + 1:
            _fail(path, f"неверный номер или отступ шага: строка блока {pos + 2}")
        count += 1
        pad = " " * (len(match[1]) + 4)
        pos += 1
        for key in ("Действие", "Проверка", "Дальше", "При ошибке"):
            if pos >= len(lines) or not lines[pos].startswith(pad):
                _fail(path, f"шаг {count}: отсутствует поле {key}")
            match_field = FIELD.fullmatch(lines[pos][len(pad):])
            if not match_field or match_field[1] != key:
                _fail(path, f"шаг {count}: неверное поле {key}")
            value = match_field[2]
            pos += 1
            while pos < len(lines) and lines[pos].startswith(pad + "  ") and lines[pos].strip():
                value += " " + lines[pos].strip()
                pos += 1
            if key in ("Дальше", "При ошибке"):
                transitions.extend(int(n) for n in TARGET.findall(value))
    if not count:
        _fail(path, "пустой блок шагов")
    if any(n < 1 or n > count for n in transitions):
        _fail(path, "переход на несуществующий шаг")


def _sections(text: str, path: str) -> tuple[str, list[tuple[str, list[str]]]]:
    if "\r" in text or "\x00" in text or "\t" in text:
        _fail(path, "недопустимые управляющие символы или переносы")
    lines = text.split("\n")
    if not lines or not lines[0].startswith("# ") or not lines[0][2:].strip():
        _fail(path, "нет заголовка файла")
    title = lines[0]
    sections: list[tuple[str, list[str]]] = []
    for line in lines[1:]:
        if line.startswith("## "):
            if not line[3:].strip():
                _fail(path, "пустой заголовок раздела")
            sections.append((line, []))
        elif not sections:
            if line:
                _fail(path, "текст вне раздела")
        else:
            sections[-1][1].append(line)
    for _, content in sections:
        while content and not content[0]:
            content.pop(0)
        while content and not content[-1]:
            content.pop()
    return title, sections


def _records(lines: list[str], path: str) -> list[tuple[str, str]]:
    result = []
    for line in lines:
        if not line:
            continue
        match = FIELD.fullmatch(line)
        if not match:
            _fail(path, "неверная запись")
        result.append((match[1], match[2]))
    if not result:
        _fail(path, "пустой раздел")
    return result


def _skill(text: str, name: str, path: str) -> Entry:
    title, sections = _sections(text, path)
    headings = [s[0] for s in sections]
    if title != "# SKILL" or headings not in (
        ["## Описание", "## Порядок работы"],
        ["## Описание", "## Порядок работы", "## Дополнительно"],
    ):
        _fail(path, "неверные или повторные разделы")
    records = _records(sections[0][1], path)
    if [r[0] for r in records] != ["Имя", "Когда применять", "Результат"]:
        _fail(path, "неверные поля описания")
    if records[0][1] != name:
        _fail(path, "имя не совпадает с каталогом")
    _validate_steps(sections[1][1], path)
    if len(sections) == 3:
        _records(sections[2][1], path)
    return Entry(name, records[1][1], records[2][1], f"{name}/SKILL.md")


def _reference(text: str, path: str) -> None:
    _, sections = _sections(text, path)
    if not sections or len({h for h, _ in sections}) != len(sections):
        _fail(path, "отсутствуют или повторяются разделы")
    for _, content in sections:
        if "- **Шаги:**" in content:
            at = content.index("- **Шаги:**")
            if at:
                _records(content[:at], path)
            _validate_steps(content[at:], path)
        else:
            _records(content, path)


def _links(skillfd: int, rel: str, text: str) -> None:
    # Conservatively reject ambiguous Markdown links rather than miss one.
    matches = list(LINK.finditer(text))
    remainder = LINK.sub("", text)
    if re.search(r"!?\[[^\]\n]*\]\s*(?:\(|\[)", remainder):
        _fail(rel, "неподдерживаемый синтаксис ссылки")
    for match in matches:
        raw = match[1]
        decoded = unquote(raw)
        parsed = urlsplit(decoded)
        if (decoded != raw or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
                or decoded.startswith("/") or "\\" in decoded or "\x00" in decoded):
            _fail(rel, "недопустимая ссылка")
        parts = decoded.split("/")
        if not parts or any(p in ("", ".", "..") for p in parts):
            _fail(rel, "небезопасный путь ссылки")
        base = rel.split("/")[:-1]
        current = os.dup(skillfd)
        try:
            all_parts = base + parts
            for component in all_parts[:-1]:
                nxt = _directory(current, component)
                os.close(current)
                current = nxt
            fd = os.open(all_parts[-1], FILE_FLAGS, dir_fd=current)
            try:
                st = os.fstat(fd)
                _trusted(st, rel, False)
                if _fingerprint(st) != _fingerprint(os.stat(all_parts[-1], dir_fd=current, follow_symlinks=False)):
                    _fail(rel, "цель ссылки изменена при проверке")
            finally:
                os.close(fd)
        finally:
            os.close(current)


def scan(skills_fd: int) -> list[Entry]:
    """Return catalogue only if every entry validates. Missing root is caller policy."""
    result: list[Entry] = []
    try:
        initial = os.fstat(skills_fd)
        _trusted(initial, "skills/", True)
        names = sorted(os.listdir(skills_fd))
    except OSError as exc:
        raise CatalogError(f"skills/: ошибка чтения каталога ({type(exc).__name__})") from exc
    for name in names:
        if not NAME.fullmatch(name):
            _fail(name, "недопустимое имя каталога")
        try:
            skillfd = _directory(skills_fd, name)
            try:
                skill_start = os.fstat(skillfd)
                files = os.listdir(skillfd)
                if any(item not in ("SKILL.md", "references") for item in files):
                    _fail(name, "неизвестный элемент каталога")
                source = _file(skillfd, "SKILL.md", f"{name}/SKILL.md")
                entry = _skill(source, name, f"{name}/SKILL.md")
                _links(skillfd, "SKILL.md", source)
                if "references" in files:
                    ref_fd = _directory(skillfd, "references")
                    try:
                        ref_start = os.fstat(ref_fd)
                        for ref in sorted(os.listdir(ref_fd)):
                            rel = f"references/{ref}"
                            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.md", ref):
                                _fail(f"{name}/{rel}", "недопустимое имя справочника")
                            text = _file(ref_fd, ref, f"{name}/{rel}")
                            _reference(text, f"{name}/{rel}")
                            _links(skillfd, rel, text)
                        if (_fingerprint(ref_start) != _fingerprint(os.fstat(ref_fd)) or
                                _fingerprint(ref_start) != _fingerprint(os.stat('references', dir_fd=skillfd, follow_symlinks=False))):
                            _fail(name, "каталог references изменён при проверке")
                    finally:
                        os.close(ref_fd)
                if (_fingerprint(skill_start) != _fingerprint(os.fstat(skillfd)) or
                        _fingerprint(skill_start) != _fingerprint(os.stat(name, dir_fd=skills_fd, follow_symlinks=False))):
                    _fail(name, "каталог скилла изменён при проверке")
                result.append(entry)
            finally:
                os.close(skillfd)
        except (OSError, UnicodeError, ValueError) as exc:
            raise CatalogError(f"{name}: ошибка доступа или кодировки ({type(exc).__name__})") from exc
    if _fingerprint(initial) != _fingerprint(os.fstat(skills_fd)):
        _fail('skills/', 'каталог изменён при проверке')
    return result
