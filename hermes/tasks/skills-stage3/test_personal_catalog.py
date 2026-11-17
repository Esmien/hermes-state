import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import personal_catalog
import skill_catalog
from test_skill_catalog import examples

MEMORY_FILE = '/home/ai_service/ai-stack/ai/webui-tools/file_memory_tool.py'
UID_A = '11111111-1111-4111-8111-111111111111'
UID_B = '22222222-2222-4222-8222-222222222222'


def load_memory():
    spec = importlib.util.spec_from_file_location('test_memory_binding', MEMORY_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PersonalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skills-users-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.memory = load_memory()
        self.memory.ROOT = str(root / 'users')
        self.memory.HOST_ROOT = '/test-host/users'
        self.memory.STATE = str(root / 'state.json')
        (root / 'users').mkdir()
        self.state = {}
        for uid, slug, ex in [(UID_A, 'user-a', examples()[0]), (UID_B, 'verify-backup', examples()[3])]:
            agents = root / 'users' / slug / '.agents'
            skill = agents / 'skills' / ('read-text-file' if uid == UID_A else 'verify-backup')
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text(ex, encoding='utf-8')
            self.state[uid] = {'user_id': uid, 'slug': slug, 'dir': '/test-host/users/' + slug, 'active': True}
        self.save_state()
        self.root = root

    def save_state(self):
        Path(self.memory.STATE).write_text(json.dumps(self.state), encoding='utf-8')

    def test_users_receive_only_own_catalogue_and_ignore_extra_path(self):
        a = personal_catalog.scan_user({'id': UID_A, 'slug': 'verify-backup', 'path': '../verify-backup'}, self.memory)
        b = personal_catalog.scan_user({'id': UID_B, 'slug': 'user-a'}, self.memory)
        self.assertEqual([x.name for x in a], ['read-text-file'])
        self.assertEqual([x.name for x in b], ['verify-backup'])

    def test_inactive_unknown_and_malformed_rejected(self):
        self.state[UID_A]['active'] = False
        self.save_state()
        for user in ({'id': UID_A}, {'id': '00000000-0000-4000-8000-000000000000'}, {'id': '../user-a'}, {}):
            with self.subTest(user=user), self.assertRaises(skill_catalog.CatalogError):
                personal_catalog.scan_user(user, self.memory)

    def test_state_path_tampering_rejected(self):
        self.state[UID_A]['dir'] = '/test-host/users/verify-backup'
        self.save_state()
        with self.assertRaises(skill_catalog.CatalogError):
            personal_catalog.scan_user({'id': UID_A}, self.memory)

    def test_untrusted_owner_and_mode_rejected(self):
        f = self.root / 'users' / 'user-a' / '.agents' / 'skills' / 'read-text-file' / 'SKILL.md'
        real_stat = skill_catalog.os.fstat
        class Altered:
            def __init__(self, st): self.st = st
            def __getattr__(self, name):
                if name == 'st_uid': return 1000
                return getattr(self.st, name)
        def fake(fd):
            st = real_stat(fd)
            return Altered(st) if st.st_ino == f.stat().st_ino else st
        with patch.object(skill_catalog.os, 'fstat', side_effect=fake):
            with self.assertRaisesRegex(skill_catalog.CatalogError, 'владелец'):
                personal_catalog.scan_user({'id': UID_A}, self.memory)

    def test_replaced_file_detected_during_read(self):
        target = self.root / 'users' / 'user-a' / '.agents' / 'skills' / 'read-text-file' / 'SKILL.md'
        replacement = self.root / 'replacement'
        replacement.write_text(examples()[0], encoding='utf-8')
        real_stat = skill_catalog.os.stat
        changed = False
        def replace_at_stat(path, *args, **kwargs):
            nonlocal changed
            if path == 'SKILL.md' and kwargs.get('follow_symlinks') is False and not changed:
                os.replace(replacement, target)
                changed = True
            return real_stat(path, *args, **kwargs)
        with patch.object(skill_catalog.os, 'stat', side_effect=replace_at_stat):
            with self.assertRaisesRegex(skill_catalog.CatalogError, 'изменён'):
                personal_catalog.scan_user({'id': UID_A}, self.memory)
        self.assertTrue(changed)

    def test_missing_skills_is_empty(self):
        self.state[UID_A]['slug'] = 'empty-user'
        self.state[UID_A]['dir'] = '/test-host/users/empty-user'
        (self.root / 'users' / 'empty-user' / '.agents').mkdir(parents=True)
        self.save_state()
        self.assertEqual(personal_catalog.scan_user({'id': UID_A}, self.memory), [])


if __name__ == '__main__':
    unittest.main()
