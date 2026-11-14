import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
import memory_tool as m

HEAD = '- **Ключ:** '


def B(text='текст', key='Ключ'):
    return f'- **{key}:** {text}'


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
        self.assertTrue(m.operate(self.user,'append','MEMORY',HEAD + 'x'*(m.RECORD_LIMIT-len(HEAD)))['ok'])
        with self.assertRaises(m.MemoryErrorSafe):
            m.operate(self.user,'append','MEMORY',HEAD + 'x'*(m.RECORD_LIMIT-len(HEAD)+1))
        self.assertTrue(m.operate(self.user,'append','PROFILE',B('ю'*1000))['ok'])
        before = (self.agents / 'PROFILE.md').read_text()
        result = m.operate(self.user,'append','PROFILE',B('z'*4000))
        self.assertTrue(result['ok'])
        self.assertTrue((self.agents / 'PROFILE.md').read_text().startswith(before))
    def test_delete_exact_and_replace(self):
        for v in ('alpha', 'beta', 'gamma'): m.operate(self.user,'append','MEMORY',B(v))
        with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'delete','MEMORY',selected=[{'number':2,'text':'wrong'}])
        m.operate(self.user,'replace','MEMORY',B('new'), [{'number':2,'text':B('beta')}])
        # Правка — новая запись и удаление старой, а не правка текста на месте.
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'], [B('alpha'),B('gamma'),B('new')])
        m.operate(self.user,'delete','MEMORY',selected=[{'number':1,'text':B('alpha')},{'number':2,'text':B('gamma')}])
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'], [B('new')])
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
        m.operate(self.user,'append','PROFILE',B('Third'))
        self.assertTrue(p.read_text().startswith(original))
        self.assertEqual(m.operate(self.user,'list','PROFILE')['entries'], ['First line\nsecond line','Another entry',B('Third')])
    def test_no_bulk_agents_write_or_bad_shape(self):
        for f in ('../PROFILE', '/etc/passwd'):
            with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'append',f,'bad')
        self.assertTrue(m.operate(self.user,'append','AGENTS',B('a'*6000))['ok'])
        with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'append','MEMORY','a\n\nb')
        # Без разметки запись не принимается: нужен пункт списка с жирным ключом.
        for bad in ('обычный абзац текста', '- пункт без ключа', '**Ключ:** без пункта', B('x') + '\nвторая строка'):
            with self.assertRaises(m.MemoryErrorSafe): m.operate(self.user,'append','MEMORY',bad)
        # Внутренний перенос (фильтр переносит унаследованные записи) допускается только явно.
        self.assertTrue(m.operate(self.user,'append','PROFILE','legacy prose',strict=False)['ok'])
        self.assertEqual(m.operate(self.user,'list','PROFILE')['entries'][-1],'legacy prose')

if __name__ == '__main__': unittest.main()

class StructuredFormatTests(MemoryTests):
    def test_sections_are_not_entries(self):
        (self.agents/'MEMORY.md').write_text('# MEMORY\n\n## Проект\n\nПервая запись.\n\n## Заметки\n\nВторая запись.\n')
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'], ['Первая запись.','Вторая запись.'])
        m.operate(self.user,'append','MEMORY',B('Третья запись.'))
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'], ['Первая запись.','Вторая запись.',B('Третья запись.')])
        m.operate(self.user,'delete','MEMORY',selected=[{'number':1,'text':'Первая запись.'}])
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'], ['Вторая запись.',B('Третья запись.')])

class BulletFormatTests(MemoryTests):
    def test_bullets_are_separate_records(self):
        (self.agents/'PROFILE.md').write_text('# PROFILE\n\n## Основная информация\n\n- Имя: Влад\n- Город: Краснодар\n\n## Телефон\n\n- iPhone 15 Pro Max\n')
        self.assertEqual(m.operate(self.user,'list','PROFILE')['entries'], ['- Имя: Влад','- Город: Краснодар','- iPhone 15 Pro Max'])
        m.operate(self.user,'delete','PROFILE',selected=[{'number':2,'text':'- Город: Краснодар'}])
        self.assertEqual(m.operate(self.user,'list','PROFILE')['entries'], ['- Имя: Влад','- iPhone 15 Pro Max'])
    def test_new_bullets_carry_bold_key(self):
        (self.agents/'PROFILE.md').write_text('# PROFILE\n\n## Основная информация\n\n- **Имя:** Влад\n')
        m.operate(self.user,'append','PROFILE',B('Краснодар','Город'))
        self.assertEqual(m.operate(self.user,'list','PROFILE')['entries'], ['- **Имя:** Влад','- **Город:** Краснодар'])
