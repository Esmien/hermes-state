"""Staged adapter to the existing file-memory identity binding; not deployed."""
import os

from skill_catalog import CatalogError, _directory, _fingerprint, _trusted, scan


def scan_user(user, memory):
    """User must be server-injected; memory is the trusted memory module, not input.

    An absent skills directory means an empty personal catalogue. All other
    access errors fail closed. No user-supplied path or slug is accepted.
    """
    try:
        agents = memory._open_dir(user)
    except Exception as exc:
        raise CatalogError('Личная память недоступна или пользователь не подтверждён') from exc
    try:
        before = os.fstat(agents)
        _trusted(before, '.agents', True)
        try:
            skills = _directory(agents, 'skills')
        except FileNotFoundError:
            if _fingerprint(before) != _fingerprint(os.fstat(agents)):
                raise CatalogError('.agents изменён при проверке')
            return []
        try:
            original = os.fstat(skills)
            result = scan(skills)
            linked = os.stat('skills', dir_fd=agents, follow_symlinks=False)
            if (_fingerprint(original) != _fingerprint(os.fstat(skills)) or
                    _fingerprint(original) != _fingerprint(linked) or
                    _fingerprint(before) != _fingerprint(os.fstat(agents))):
                raise CatalogError('Личный каталог изменён при проверке')
            return result
        finally:
            os.close(skills)
    except OSError as exc:
        raise CatalogError(f'Личный каталог недоступен ({type(exc).__name__})') from exc
    finally:
        os.close(agents)
