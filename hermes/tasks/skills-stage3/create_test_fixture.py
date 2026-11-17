"""Create one non-secret read-only catalogue fixture in the authorized Test account.

Does not overwrite any existing path; uses the deployed memory binding. The
fixture intentionally remains in Test's personal catalogue for further checks.
"""
import importlib.util
import os
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location('memory_binding', '/home/ai_service/ai-stack/ai/webui-tools/file_memory_tool.py')
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)
memory.STATE = '/home/ai_service/sandbox-users/state.json'
memory.ROOT = '/home/ai_service/sandbox/users'
user = {'id': '695924f7-9a9b-4ba4-bc54-a5bc2a440d56'}
doc = Path('/root/.hermes/docs/skill-format-specification.md').read_text(encoding='utf-8')
examples = re.findall(r'```markdown\n(.*?)\n```', doc.split('## Пример 1. Простой скилл', 1)[1], re.S)
assert len(examples) == 4
agents = memory._open_dir(user)
flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
try:
    os.mkdir('skills', 0o755, dir_fd=agents)
    skills = os.open('skills', flags, dir_fd=agents)
    try:
        os.mkdir('inspect-json', 0o755, dir_fd=skills)
        skill = os.open('inspect-json', flags, dir_fd=skills)
        try:
            os.mkdir('references', 0o755, dir_fd=skill)
            refs = os.open('references', flags, dir_fd=skill)
            try:
                for parent, name, text in ((skill, 'SKILL.md', examples[1]), (refs, 'json-errors.md', examples[2])):
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent)
                    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                        stream.write(text + '\n')
                        stream.flush()
                        os.fsync(stream.fileno())
            finally:
                os.close(refs)
        finally:
            os.close(skill)
    finally:
        os.close(skills)
finally:
    os.close(agents)
print('Fixture created for Test: inspect-json plus one reference; no existing file overwritten.')
