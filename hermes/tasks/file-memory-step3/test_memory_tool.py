import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
import memory_tool as m

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/root/.hermes/cache/scratch')
        self.root = Path(self.tmp.name) / 'users'
        self.root.mkdir()
        self.uid = str(uuid.uuid4())
        self.user = {'id': self.uid}
        self.workspace = self.root / 'alice'
        self.agents = self.workspace / '.agents'
        self.agents.mkdir(parents=True)
        for name in ('AGENTS', 'MEMORY', 'PROFILE'):
            (self.agents / (name + '.md')).write_text('# ' + name + '\n\n', encoding='utf-8')
        m.ROOT = str(self.root)
        m.HOST_ROOT = '/host/users'
        m.STATE = str(Path(self.tmp.name) / 'state.json')
        self.state = {self.uid: {'user_id': self.uid, 'active': True, 'slug': 'alice', 'dir': '/host/users/alice'}}
        self.save_state()
    def save_state(self):
        Path(m.STATE).write_text(json.dumps(self.state))
    def tearDown(self):
        self.tmp.cleanup()
    def test_append_limit_and_profile(self):
        self.assertTrue(m.operate(self.user,'append','MEMORY','x'*260)['ok'])
        with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'append','MEMORY','x'*261)
        self.assertTrue(m.operate(self.user,'append','PROFILE','ю'*1000)['ok'])
        before = (self.agents / 'PROFILE.md').read_text()
        result = m.operate(self.user,'append','PROFILE','z'*4000)
        self.assertTrue(result['ok'])
        self.assertTrue((self.agents / 'PROFILE.md').read_text().startswith(before))
    def test_delete_exact_and_replace(self):
        for v in ('alpha', 'beta', 'gamma'): m.operate(self.user,'append','MEMORY',v)
        with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'delete','MEMORY',selected=[{'number':2,'text':'wrong'}])
        m.operate(self.user,'replace','MEMORY','new', [{'number':2,'text':'beta'}])
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'], ['alpha','new','gamma'])
        m.operate(self.user,'delete','MEMORY',selected=[{'number':1,'text':'alpha'},{'number':3,'text':'gamma'}])
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'], ['new'])
    def test_user_and_path_rejection(self):
        self.assertRaises(m.MemoryErrorSafe,m.operate,{'id':str(uuid.uuid4())},'list','MEMORY')
        self.state[self.uid]['slug']='../other'; self.save_state()
        self.assertRaises(m.MemoryErrorSafe,m.operate,self.user,'list','MEMORY')
    def test_symlink_and_hardlink_rejected(self):
        p=self.agents/'MEMORY.md'; p.unlink(); p.symlink_to(self.agents/'PROFILE.md')
        with self.assertRaises(OSError): m.operate(self.user,'list','MEMORY')
        p.unlink(); os.link(self.agents/'PROFILE.md',p)
        with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'list','MEMORY')
    def test_migrated_multiline_profile_is_preserved(self):
        p=self.agents/'PROFILE.md'; original='# PROFILE\n\nFirst line\nsecond line\n\nAnother entry\n'; p.write_text(original)
        m.operate(self.user,'append','PROFILE','Third')
        self.assertTrue(p.read_text().startswith(original))
        self.assertEqual(m.operate(self.user,'list','PROFILE')['entries'], ['First line\nsecond line','Another entry','Third'])
    def test_no_bulk_agents_write_or_bad_shape(self):
        for f in ('../PROFILE', '/etc/passwd'):
            with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'append',f,'bad')
        self.assertTrue(m.operate(self.user,'append','AGENTS','a'*6000)['ok'])
        with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'append','MEMORY','a\n\nb')

if __name__ == '__main__': unittest.main()
