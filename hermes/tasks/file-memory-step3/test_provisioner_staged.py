import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('staged_provisioner', Path(__file__).with_name('provisioner-staged.py'))
provisioner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provisioner)

class ProvisionerStagedTests(unittest.TestCase):
    def test_long_profile_preserved_on_create_and_repeat(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as root:
            prompt = 'данные_' * 1000
            with patch.object(provisioner, 'user_system_prompt', return_value=prompt):
                provisioner.ensure_memory_files(root, '11111111-1111-1111-1111-111111111111')
                agents = Path(root, '.agents')
                self.assertEqual((agents / 'PROFILE.md').read_text(), '# PROFILE\n\n' + prompt)
                self.assertIn('MEMORY имеет преимущество над PROFILE', (agents / 'AGENTS.md').read_text())
                before = {p.name: p.read_bytes() for p in agents.iterdir()}
            with patch.object(provisioner, 'user_system_prompt', side_effect=AssertionError('must not overwrite')):
                provisioner.ensure_memory_files(root, '11111111-1111-1111-1111-111111111111')
            self.assertEqual(before, {p.name: p.read_bytes() for p in agents.iterdir()})

if __name__ == '__main__':
    unittest.main()
