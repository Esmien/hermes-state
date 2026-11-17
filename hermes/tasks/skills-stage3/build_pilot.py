"""Build a standalone Open WebUI catalogue pilot; no deployment."""
from pathlib import Path
import ast

p = Path(__file__).resolve().parent
memory = Path('/home/ai_service/ai-stack/ai/webui-tools/file_memory_tool.py').read_text()
catalog = (p / 'skill_catalog.py').read_text().replace('from __future__ import annotations\n', '')
adapter = (p / 'personal_catalog.py').read_text().replace('from skill_catalog import CatalogError, _directory, _fingerprint, _trusted, scan\n', '')
wrapper = '''\nimport types\n_pilot_memory = types.SimpleNamespace(_open_dir=_open_dir)\n\nclass Tools:\n    def list_personal_skills(self, __user__: dict = None) -> str:\n        """List validated personal skill descriptions for the current user."""\n        try:\n            entries = scan_user(__user__, _pilot_memory)\n            return json.dumps({"skills": [{"name": e.name, "trigger": e.trigger, "result": e.result} for e in entries]}, ensure_ascii=False)\n        except Exception:\n            return json.dumps({"error": "Личный каталог скиллов недоступен или некорректен"}, ensure_ascii=False)\n'''
content = 'from __future__ import annotations\n' + memory + '\n' + catalog + '\n' + adapter + wrapper
ast.parse(content)
out = p / 'pilot_tool.py'
if out.exists():
    raise RuntimeError('Refusing to overwrite existing built artifact')
out.write_text(content, encoding='utf-8')
print('Built and syntax-checked pilot_tool.py; not deployed.')
