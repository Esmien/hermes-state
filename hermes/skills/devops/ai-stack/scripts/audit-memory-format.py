"""Аудит формата записей в .agents всех песочниц: каждая запись должна быть
одним пунктом Markdown `- **Ключ:** текст` без переносов строк.

Запуск (root):
    python3 scripts/audit-memory-format.py [--root /home/ai_service/sandbox/users] \
        [--tool /home/ai_service/ai-stack/ai/webui-tools/file_memory_tool.py]

Парсер и регулярка берутся из канонического Tool памяти, а не копируются сюда:
правила разбора меняются в коде, аудит обязан следовать за ними.
Код возврата 1 = есть записи не в формате.
"""
import argparse
import importlib.util
import os
import sys


def load_tool(path):
    spec = importlib.util.spec_from_file_location('file_memory_tool', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='/home/ai_service/sandbox/users')
    ap.add_argument('--tool', default='/home/ai_service/ai-stack/ai/webui-tools/file_memory_tool.py')
    args = ap.parse_args()

    tool = load_tool(args.tool)
    total = bad_total = 0
    for slug in sorted(os.listdir(args.root)):
        directory = os.path.join(args.root, slug, '.agents')
        if not os.path.isdir(directory):
            continue
        parts = []
        for name in ('AGENTS', 'MEMORY', 'PROFILE'):
            path = os.path.join(directory, name + '.md')
            if not os.path.exists(path):
                continue
            try:
                records = [span.group() for span in tool._records(open(path, encoding='utf-8').read(), name)[2]]
            except Exception as exc:  # noqa: BLE001 - битый файл тоже дефект
                print(f'{slug:22} {name}: ОШИБКА РАЗБОРА {type(exc).__name__}: {exc}')
                bad_total += 1
                continue
            bad = [r for r in records if not tool.RECORD_FORMAT.fullmatch(r)]
            total += len(records)
            bad_total += len(bad)
            parts.append(f'{name}={len(records)}' + (f' (плохих {len(bad)})' if bad else ''))
            for record in bad[:3]:
                print(f'  {slug} {name}: {record[:90]}')
        print(f'{slug:22} ' + ' '.join(parts))

    print(f'всего записей: {total}, не в формате: {bad_total}')
    return 1 if bad_total else 0


if __name__ == '__main__':
    sys.exit(main())
