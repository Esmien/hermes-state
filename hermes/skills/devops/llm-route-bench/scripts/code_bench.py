#!/usr/bin/env python3
"""Hidden-test bench for code generation through LiteLLM.

Run INSIDE the sandbox container:
    docker cp code_bench.py open-terminal-sandbox:/workspace/code_bench.py
    K=$(sed -n 's/^LITELLM_MASTER_KEY=//p' /home/ai_service/ai-stack/ai/.env | head -1)
    docker exec -e LITELLM_MASTER_KEY="$K" open-terminal-sandbox python3 /workspace/code_bench.py

One request per (model, task): no retry, no system prompt, reasoning_effort=high.
Score = hidden tests passed on the first attempt. Results go to /workspace/bench/results.jsonl.

Usage:
    --task truncate_utf8,csv_line,legacy_refactor,needle   subset of tasks
    --models sol-6.1,terra                                subset of models
    --out /workspace/bench/results.jsonl
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

LITELLM = 'http://litellm:4000/v1/chat/completions'
KEY = os.environ['LITELLM_MASTER_KEY']

MODELS = [
    ('deepseek-v4.1-flash', 'deepseek/deepseek-v4.1-flash'),
    ('luna', 'openai/gpt-6-luna'),
    ('haiku-5.5', 'anthropic/claude-haiku-5.5'),
    ('muse-spark-1.3', 'opencode/muse-spark-1.3-contributor'),
    ('mimo-v2.6-flash', 'xiaomi/mimo-v2.6-flash'),
    ('glm-5.3-flash', 'zai/glm-5.3-flash'),
    ('astra', 'openai/gpt-6-astra'),
    ('sol-6.1', 'openai/gpt-6.1-sol'),
    ('argon', 'google/gemini-4-argon'),
    ('terra', 'openai/gpt-6.1-terra'),
]

LEGACY = '''from decimal import Decimal, ROUND_HALF_UP

_MISSING = -1


def normalize_sku(s):
    return s.strip().upper()


def add_item(cart, sku, qty, price):
    key = normalize_sku(sku)
    if qty < 0:
        qty = 0
    cart.append({"sku": key, "qty": qty, "price": price})
    return cart


def find_item(cart, sku):
    key = normalize_sku(sku)
    for i, item in enumerate(cart):
        if item["sku"] == key:
            return i
    return _MISSING


def remove_item(cart, sku):
    idx = find_item(cart, sku)
    if idx == -1:
        return False
    cart.pop(idx)
    return True


def total(cart):
    acc = Decimal("0")
    for item in cart:
        acc += Decimal(str(item["price"])) * item["qty"]
    return float(acc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sorted_items(cart):
    return sorted(cart, key=lambda item: item["sku"].lower())
'''


def build_pipeline(handlers=20):
    """Module with one planted bug: _backoff returns seconds, sleep divides by 1000."""
    parts = ['"""Пайплайн обработки событий."""\nimport time\n\nRETRY_LIMIT = 3\nBASE_DELAY = 2\n',
             '\nHANDLERS = {}\n\n\ndef handler(name):\n    def wrap(fn):\n'
             '        HANDLERS[name] = fn\n        return fn\n    return wrap\n']
    for i in range(handlers):
        parts.append(
            f'\n\n@handler("op_{i:02d}")\n'
            f'def handle_op_{i:02d}(payload):\n'
            f'    """Обработчик {i:02d}: масштабирует входное значение."""\n'
            f'    factor = {i + 1}\n'
            f'    value = payload.get("value", 0)\n'
            f'    if value < 0:\n        value = 0\n'
            f'    return value * factor\n')
    parts.append('''

def _backoff(attempt):
    """Задержка перед повтором, в миллисекундах."""
    return BASE_DELAY ** attempt


def process_event(event, fail_times=0):
    calls = {"n": 0}

    def attempt_once():
        calls["n"] += 1
        fn = HANDLERS.get(event.get("op"))
        if fn is None:
            raise KeyError(event.get("op"))
        if calls["n"] <= fail_times:
            raise RuntimeError("transient")
        return fn(event.get("payload") or {})

    for attempt in range(1, RETRY_LIMIT):
        try:
            return attempt_once()
        except RuntimeError:
            time.sleep(_backoff(attempt))
    raise RuntimeError("exhausted")


def process_batch(events):
    results, errors = [], []
    for event in events:
        try:
            results.append(process_event(event))
        except Exception as exc:
            errors.append({"op": event.get("op"), "error": type(exc).__name__})
    return {"results": results, "errors": errors}


def aggregate(results):
    acc = 0.0
    for value in results:
        acc += value
    return round(acc, 2)
''')
    return ''.join(parts)


TASKS = {
    'truncate_utf8': {
        'prompt': '''Реализуй на Python 3.12 функцию:

def truncate_utf8(s: str, max_bytes: int) -> str

- Самый длинный префикс s, занимающий в UTF-8 не более max_bytes байт.
- Символы не разрезаются.
- max_bytes <= 0 -> ValueError.
Ответ: только код в одном блоке ```python, без пояснений.''',
        'tests': r'''
def run(m):
    t = m.truncate_utf8
    return [
        ("ascii_cut", lambda: t("hello", 3) == "hel"),
        ("exact", lambda: t("hello", 5) == "hello"),
        ("cyrillic", lambda: t("привет", 5) == "пр"),
        ("emoji_nosplit", lambda: t("a\U0001F600b", 4) == "a"),
        ("emoji_fits", lambda: t("a\U0001F600b", 5) == "a\U0001F600"),
        ("empty", lambda: t("", 10) == ""),
        ("zero", lambda: _raises(t, "x", 0)),
        ("negative", lambda: _raises(t, "x", -3)),
        ("multibyte", lambda: t("\u00e9\u00e9\u00e9", 3) == "\u00e9"),
    ]
''',
    },
    'csv_line': {
        'prompt': '''Реализуй на Python 3.12 функцию:

def parse_csv_line(line: str) -> list[str]

RFC 4180 (подмножество): запятая — разделитель, поле в двойных кавычках, "" -> ",
запятые и переводы строк внутри кавычек допустимы, пустая строка -> [''].
Незакрытая кавычка, символ после закрывающей кавычки, кавычка вне кавычек -> ValueError.
Пробелы вне кавычек сохраняются.
Ответ: только код в одном блоке ```python, без пояснений.''',
        'tests': r'''
def run(m):
    t = m.parse_csv_line
    return [
        ("simple", lambda: t("a,b,c") == ["a", "b", "c"]),
        ("empty", lambda: t("") == [""]),
        ("trailing", lambda: t("a,") == ["a", ""]),
        ("quoted_comma", lambda: t('"a,b",c') == ["a,b", "c"]),
        ("escaped", lambda: t('"he said ""hi""",x') == ['he said "hi"', "x"]),
        ("spaces", lambda: t(" a , b ") == [" a ", " b "]),
        ("multiline", lambda: t('"a\nb",c') == ["a\nb", "c"]),
        ("unterminated", lambda: _raises(t, '"abc')),
        ("after_quote", lambda: _raises(t, '"a"b,c')),
        ("bare_quote", lambda: _raises(t, 'a"b')),
    ]
''',
    },
    'legacy_refactor': {
        'prompt': '''Ниже модуль корзины, он в проде два года.

```python
{code}```

Перепиши чисто и читаемо, НО поведение обязано остаться идентичным, включая странности
(типы возврата, sentinel -1, мутации аргументов, округление, стабильность сортировки,
обнуление отрицательных). Публичный API менять нельзя.
Ответ: только новый файл целиком в одном блоке ```python, без пояснений.''',
        'code': LEGACY,
        'tests': r'''
def run(m):
    def add_basic():
        cart = []
        out = m.add_item(cart, " a1 ", 2, 10.5)
        return out is cart and cart[0]["sku"] == "A1" and cart[0]["qty"] == 2

    def negative_clamped():
        cart = []
        m.add_item(cart, "x", -5, 1.0)
        return cart[0]["qty"] == 0

    def find_sentinel():
        cart = []
        m.add_item(cart, "a", 1, 1.0)
        return m.find_item(cart, "a") == 0 and m.find_item([], "z") == -1

    def remove_ok():
        cart = []
        m.add_item(cart, "a", 1, 1.0)
        m.add_item(cart, "b", 1, 1.0)
        return m.remove_item(cart, "a") is True and [i["sku"] for i in cart] == ["B"]

    def remove_missing():
        return m.remove_item([], "nope") is False

    def total_basic():
        cart = []
        m.add_item(cart, "a", 3, 1.15)
        m.add_item(cart, "b", 2, 0.5)
        return m.total(cart) == 4.45

    def total_half_up():
        cart = []
        m.add_item(cart, "a", 1, 0.005)
        return m.total(cart) == 0.01

    def total_artifact():
        cart = []
        m.add_item(cart, "a", 3, 0.1)
        return m.total(cart) == 0.3

    def total_empty():
        return m.total([]) == 0.0

    def sort_case():
        cart = []
        for sku in ["b", "A", "c"]:
            m.add_item(cart, sku, 1, 1.0)
        return [i["sku"] for i in m.sorted_items(cart)] == ["A", "B", "C"]

    def sort_stable():
        cart = []
        m.add_item(cart, "aa", 1, 1.0)
        m.add_item(cart, "AA", 2, 2.0)
        return [i["qty"] for i in m.sorted_items(cart)] == [1, 2]

    def normalize_zeros():
        cart = []
        m.add_item(cart, " 007 ", 1, 1.0)
        return cart[0]["sku"] == "007"

    def sorter_is_new_list():
        cart = []
        m.add_item(cart, "a", 1, 1.0)
        return m.sorted_items(cart) is not cart and len(cart) == 1

    return [(n, f) for n, f in [
        ("add_basic", add_basic), ("negative_clamped", negative_clamped),
        ("find_sentinel", find_sentinel), ("remove_ok", remove_ok),
        ("remove_missing", remove_missing), ("total_basic", total_basic),
        ("total_half_up", total_half_up), ("total_artifact", total_artifact),
        ("total_empty", total_empty), ("sort_case", sort_case),
        ("sort_stable", sort_stable), ("normalize_zeros", normalize_zeros),
        ("sorter_is_new_list", sorter_is_new_list),
    ]]
''',
    },
    'needle': {
        'prompt': '''Ниже рабочий модуль. В нём ровно один баг: повторы при сбое работают не так,
как заявлено в докстрингах, а задержка получается не той величины.

```python
{code}```

Найди причину и исправь. Повторных попыток ровно RETRY_LIMIT, задержка растёт
экспоненциально и измеряется в миллисекундах, sleep получает секунды.
Публичный API не менять. Не добавляй зависимостей.
Ответ: только исправленный файл целиком в одном блоке ```python, без пояснений.''',
        'factory': build_pipeline,
        'tests': r'''
import time as _time

def run(m):
    real = _time.sleep

    def wrap(fn):
        def inner():
            calls = []
            _time.sleep = lambda s: calls.append(s)
            try:
                return fn(calls)
            finally:
                _time.sleep = real
        return inner

    def retries_three(calls):
        m.process_event({"op": "op_01", "payload": {"value": 2}}, fail_times=2)
        return True

    def fail_all(calls):
        try:
            m.process_event({"op": "op_01", "payload": {}}, fail_times=99)
            return False
        except RuntimeError:
            return True

    def sleeps_are_ms(calls):
        try:
            m.process_event({"op": "op_01", "payload": {}}, fail_times=99)
        except RuntimeError:
            pass
        return len(calls) >= 2 and abs(calls[0] - 0.2) < 1e-9 and abs(calls[1] - 0.4) < 1e-9

    def backoff_values(calls):
        return abs(m._backoff(1) - 200) < 1e-9 and abs(m._backoff(2) - 400) < 1e-9

    def handler_works(calls):
        return m.process_event({"op": "op_07", "payload": {"value": 3}}) == 24

    def batch_results(calls):
        ev = [{"op": "op_00", "payload": {"value": 5}}, {"op": "op_01", "payload": {"value": 2}}]
        return m.process_batch(ev)["results"] == [5, 4]

    def aggregate_rounding(calls):
        return m.aggregate([0.1, 0.2]) == 0.3

    names = [("retries_three", retries_three), ("fail_all", fail_all),
             ("sleeps_are_ms", sleeps_are_ms), ("backoff_values", backoff_values),
             ("handler_works", handler_works), ("batch_results", batch_results),
             ("aggregate_rounding", aggregate_rounding)]
    return [(n, wrap(f)) for n, f in names]
''',
    },
}

HELPERS_HEAD = '''
import json
import sys


def _raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ValueError:
        return True
    except Exception:
        return False
    return False
'''

HELPERS_TAIL = '''
def main():
    import importlib.util
    spec = importlib.util.spec_from_file_location("solution", sys.argv[1])
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        print(json.dumps({"import_error": f"{type(exc).__name__}: {exc}", "results": []}))
        return
    out = []
    for name, fn in run(mod):
        try:
            out.append({"name": name, "ok": bool(fn())})
        except Exception as exc:
            out.append({"name": name, "ok": False, "err": f"{type(exc).__name__}: {exc}"})
    print(json.dumps({"import_error": None, "results": out}))


main()
'''


def call(model, prompt):
    body = {
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'reasoning_effort': 'high',
        'stream': False,
    }
    headers = {
        'Authorization': 'Bearer ' + KEY,
        'Content-Type': 'application/json',
        'x-opencode-session': 'code-bench-0000-0000-0000-000000000000',
    }
    started = time.time()
    req = urllib.request.Request(LITELLM, json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=1800) as resp:
        data = json.load(resp)
    text = data['choices'][0]['message'].get('content') or ''
    return text, data.get('usage') or {}, time.time() - started


def extract(text):
    blocks = re.findall(r'```(?:python|py)?\s*\n(.*?)```', text, re.S)
    return blocks[-1] if blocks else text


def run_one(slug, model, name, task, workdir):
    code_or = None
    if 'factory' in task:
        code_or = task['factory']()
    prompt = task['prompt'].format(code=code_or) if '{code}' in task['prompt'] else task['prompt']
    try:
        text, usage, sec = call(model, prompt)
    except Exception as exc:
        detail = exc.read()[:200].decode('utf-8', 'ignore') if hasattr(exc, 'read') else ''
        return {'model': slug, 'task': name, 'error': f'{type(exc).__name__}: {exc} {detail}'}

    outdir = os.path.join(workdir, slug)
    os.makedirs(outdir, exist_ok=True)
    solution = os.path.join(outdir, name + '.py')
    with open(solution, 'w', encoding='utf-8') as fh:
        fh.write(extract(text))
    testfile = os.path.join(outdir, 'test_' + name + '.py')
    with open(testfile, 'w', encoding='utf-8') as fh:
        fh.write(HELPERS_HEAD + task['tests'] + HELPERS_TAIL)

    try:
        proc = subprocess.run([sys.executable, testfile, solution],
                              capture_output=True, text=True, timeout=180)
        lines = (proc.stdout or '').strip().splitlines()
        data = json.loads(lines[-1]) if lines else {'import_error': 'no output', 'results': []}
    except subprocess.TimeoutExpired:
        data = {'import_error': 'timeout', 'results': []}

    details = usage.get('completion_tokens_details') or {}
    return {
        'model': slug, 'task': name,
        'passed': sum(1 for r in data['results'] if r['ok']),
        'total': len(data['results']),
        'import_error': data.get('import_error'),
        'fails': [r['name'] for r in data['results'] if not r['ok']],
        'tokens': usage.get('total_tokens'),
        'reasoning': details.get('reasoning_tokens'),
        'sec': round(sec, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', default=','.join(TASKS))
    ap.add_argument('--models', default=','.join(slug for slug, _ in MODELS))
    ap.add_argument('--out', default='/workspace/bench/results.jsonl')
    args = ap.parse_args()

    tasks = [t.strip() for t in args.task.split(',') if t.strip()]
    wanted = {m.strip() for m in args.models.split(',') if m.strip()}
    workdir = os.path.dirname(args.out)
    os.makedirs(workdir, exist_ok=True)

    with open(args.out, 'w', encoding='utf-8') as out:
        for slug, model in MODELS:
            if slug not in wanted:
                continue
            for name in tasks:
                if name not in TASKS:
                    print(f'unknown task {name}', flush=True)
                    continue
                row = run_one(slug, model, name, TASKS[name], workdir)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
                out.flush()
    print('BENCH_DONE', flush=True)


if __name__ == '__main__':
    main()
