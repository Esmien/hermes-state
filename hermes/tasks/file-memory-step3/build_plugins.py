"""Build self-contained Open WebUI plugins without installing them."""
from pathlib import Path
import ast

here=Path(__file__).resolve().parent
tool=(here/'memory_tool.py').read_text(encoding='utf-8')
flt=(here/'memory_filter.py').read_text(encoding='utf-8')
needle='import memory_tool as memory'
if flt.count(needle) != 1:
    raise RuntimeError('Unexpected filter import')
# Open WebUI stores plugins independently in its database; embed a private copy
# of the shared logic in the Filter rather than depending on a container path.
shared=tool.replace('"""Open WebUI file memory tool. Staged for isolated tests; not deployed."""','',1)
namespace='import types\nmemory = types.SimpleNamespace(**{k: globals()[k] for k in ("FILES", "_uid", "_open_dir", "_read", "_records", "_load_state", "_save_state")})'
combined=shared+'\n\n'+flt.replace(needle,namespace,1)
ast.parse(combined)
# The caller chooses where generated outputs live; never touch live plugins.
out=here/'built'
out.mkdir(exist_ok=True)
(out/'memory_tool.py').write_text(tool,encoding='utf-8')
(out/'memory_filter.py').write_text(combined,encoding='utf-8')
print('generated and syntax-checked Tool and Filter in',out)
