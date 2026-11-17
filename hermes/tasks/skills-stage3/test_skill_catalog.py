import os
from pathlib import Path
import re
import tempfile
import unittest

import skill_catalog as catalog

SPEC = Path('/root/.hermes/docs/skill-format-specification.md')


def examples():
    doc = SPEC.read_text(encoding='utf-8')
    doc = doc.split('## Пример 1. Простой скилл', 1)[1]
    doc = doc.split('## Проверки при реализации валидатора', 1)[0]
    return re.findall(r'```markdown\n(.*?)\n```', doc, re.S)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skills-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.samples = examples()

    def make(self, name='read-text-file', text=None):
        directory = self.root / name
        directory.mkdir()
        (directory / 'SKILL.md').write_text(self.samples[0] if text is None else text, encoding='utf-8')
        return directory

    def scan(self):
        return catalog.scan(self.fd)

    def bad(self, pattern=None):
        with self.assertRaises(catalog.CatalogError) as context:
            self.scan()
        if pattern:
            self.assertIn(pattern, str(context.exception))

    def test_empty_catalog(self):
        self.assertEqual(self.scan(), [])

    def test_three_examples_with_reference(self):
        self.make()
        d = self.make('inspect-json', self.samples[1])
        (d / 'references').mkdir()
        (d / 'references' / 'json-errors.md').write_text(self.samples[2], encoding='utf-8')
        self.make('verify-backup', self.samples[3])
        found = self.scan()
        self.assertEqual([e.name for e in found], ['inspect-json', 'read-text-file', 'verify-backup'])
        self.assertTrue(all(e.trigger and e.result and e.path.endswith('/SKILL.md') for e in found))

    def test_missing_skill(self):
        (self.root / 'absent').mkdir()
        self.bad('absent')

    def test_mismatch_rejects_duplicate_claimed_name(self):
        self.make()
        self.make('other')
        self.bad('имя не совпадает')

    def test_invalid_folder(self):
        (self.root / 'Upper').mkdir()
        self.bad('имя')

    def test_unreadable_catalog_descriptor(self):
        with self.assertRaises(catalog.CatalogError):
            catalog.scan(-1)

    def test_symlinked_references_directory(self):
        d = self.make('inspect-json', self.samples[1])
        (d / 'references').symlink_to('/etc', target_is_directory=True)
        self.bad('inspect-json')

    def test_bad_heading(self):
        self.make(text=self.samples[0].replace('## Описание', '## Другое'))
        self.bad('разделы')

    def test_duplicate_heading(self):
        self.make(text=self.samples[0] + '\n## Описание\n- **Имя:** повтор\n')
        self.bad('разделы')

    def test_missing_or_empty_field(self):
        for old, new in [('- **Результат:**', '- **Итог:**'), ('- **Результат:** Содержимое файла получено либо сообщена конкретная ошибка чтения.', '- **Результат:** ')]:
            with self.subTest(old=old):
                directory = self.make(text=self.samples[0].replace(old, new))
                self.bad()
                (directory / 'SKILL.md').unlink()
                directory.rmdir()

    def test_field_order(self):
        text = self.samples[0].replace('- **Проверка:**', '- **Верификация:**', 1)
        self.make(text=text)
        self.bad('поле')

    def test_number_gap_and_bad_indent(self):
        for old, new in [('  2. Передать результат.', '  3. Передать результат.'), ('     - **Действие:**', '    - **Действие:**')]:
            with self.subTest(new=new):
                directory = self.make(text=self.samples[0].replace(old, new, 1))
                self.bad()
                (directory / 'SKILL.md').unlink()
                directory.rmdir()

    def test_multiline_field_and_ten_steps(self):
        block = ('  {n}. Название.\n{pad}- **Действие:** Первая строка.\n{cont}Продолжение.\n'
                 '{pad}- **Проверка:** Выполнено.\n{pad}- **Дальше:** Завершить.\n'
                 '{pad}- **При ошибке:** Остановиться.\n')
        steps = ''.join(block.format(n=n, pad=' ' * (len(str(n)) + 4), cont=' ' * (len(str(n)) + 6)) for n in range(1, 11))
        text = self.samples[0].split('- **Шаги:**')[0] + '- **Шаги:**\n' + steps
        self.make(text=text)
        self.assertEqual(len(self.scan()), 1)

    def test_nonexistent_transition(self):
        self.make(text=self.samples[0].replace('шагу 2', 'шагу 99'))
        self.bad('несуществующий')

    def test_bad_reference_target(self):
        self.make('inspect-json', self.samples[1])
        self.bad('inspect-json')

    def test_reference_invalid(self):
        d = self.make('inspect-json', self.samples[1])
        (d / 'references').mkdir()
        (d / 'references' / 'json-errors.md').write_text('# Ошибка\n\n## Плохо\nобычный текст\n')
        self.bad('неверная запись')

    def test_dotdot_and_absolute_link(self):
        for target in ('../outside.md', '/etc/passwd', 'references/%2e%2e/escape', 'https://example.org/'):
            with self.subTest(target=target):
                d = self.make(text=self.samples[0] + '\n## Дополнительно\n- **Справочник:** [x](' + target + ')\n')
                self.bad()
                (d / 'SKILL.md').unlink()
                d.rmdir()

    def test_symlinked_skill_directory(self):
        (self.root / 'external').symlink_to('/etc', target_is_directory=True)
        self.bad('external')

    def test_symlinked_reference_file(self):
        d = self.make('inspect-json', self.samples[1])
        (d / 'references').mkdir()
        (d / 'references' / 'json-errors.md').symlink_to('/etc/passwd')
        self.bad('inspect-json')

    def test_hardlink_rejected(self):
        d = self.make()
        os.link(d / 'SKILL.md', self.root / 'other-file')
        self.bad()

    def test_unsafe_extra_does_not_silently_skip(self):
        self.make()
        (self.root / 'unexpected').write_text('not a directory')
        self.bad('unexpected')

    def test_bad_utf8(self):
        d = self.make()
        (d / 'SKILL.md').write_bytes(b'\xff')
        self.bad('кодировки')

    def test_reject_unsupported_reference_link_syntax(self):
        self.make(text=self.samples[0] + '\n## Дополнительно\n- **Справочник:** [x][ref]\n')
        self.bad('синтаксис')


if __name__ == '__main__':
    unittest.main()
