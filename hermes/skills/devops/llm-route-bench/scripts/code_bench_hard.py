#!/usr/bin/env python3
"""Hard-tier code bench: 4 tasks engineered to separate top models.

Unlike code_bench.py (where every frontier model scores 100% on the easy tier),
these tasks target the known blind spots: byte-level streaming with resync,
concurrency under a frozen clock, behavioural preservation against decoy
"improvements", and operator precedence / associativity traps.

Run INSIDE the sandbox container:
    docker cp code_bench_hard.py open-terminal-sandbox:/workspace/
    K=$(sed -n 's/^LITELLM_MASTER_KEY=//p' /home/ai_service/ai-stack/ai/.env | head -1)
    docker exec -e LITELLM_MASTER_KEY="$K" open-terminal-sandbox \
        python3 /workspace/code_bench_hard.py --models sol-6.1,terra

Self-test (no network, no spend) — reference must score 100%, broken variants
must fail their declared tests:
    python3 code_bench_hard.py --selftest

One request per (model, task): no retry, no system prompt, reasoning_effort=high.
Score = hidden tests passed on the first attempt.
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
KEY = os.environ.get('LITELLM_MASTER_KEY', '')

MODELS = [
    ('sol-6.1', 'openai/gpt-6.1-sol'),
    ('terra', 'openai/gpt-6.1-terra'),
    ('astra', 'openai/gpt-6-astra'),
    ('sonnet-5.5', 'anthropic/claude-sonnet-5.5'),
]

# ---------------------------------------------------------------- task 1: frames

FRAME_REF = r'''
MAGIC = b'\xAA\x55'
MAX_PAYLOAD = 4096


def _crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


class FrameDecoder:
    def __init__(self):
        self._buf = bytearray()

    def feed(self, data):
        self._buf += data
        buf = self._buf
        out = []
        while True:
            i = buf.find(MAGIC)
            if i < 0:
                if buf.endswith(MAGIC[:1]):
                    del buf[:len(buf) - 1]
                else:
                    buf.clear()
                break
            if i:
                del buf[:i]
            if len(buf) < 5:
                break
            length = int.from_bytes(buf[3:5], 'big')
            if length > MAX_PAYLOAD:
                del buf[:1]
                continue
            total = 5 + length + 2
            if len(buf) < total:
                break
            typ = buf[2]
            payload = bytes(buf[5:5 + length])
            crc = int.from_bytes(buf[5 + length:7 + length], 'big')
            if _crc16(bytes([typ]) + bytes(buf[3:5]) + payload) == crc:
                out.append({'type': typ, 'payload': payload})
            del buf[:total]
        return out
'''

FRAME_BROKEN = FRAME_REF.replace(
    "            if _crc16(bytes([typ]) + bytes(buf[3:5]) + payload) == crc:",
    "            if True:")

FRAME_TESTS = r'''
def _crc(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _frame(t, payload):
    body = bytes([t]) + len(payload).to_bytes(2, "big") + payload
    return b"\xAA\x55" + body + _crc(body).to_bytes(2, "big")


def run(m):
    def d():
        return m.FrameDecoder()

    def one():
        return d().feed(_frame(1, b"abc")) == [{"type": 1, "payload": b"abc"}]

    def empty_payload():
        return d().feed(_frame(7, b"")) == [{"type": 7, "payload": b""}]

    def two_one_chunk():
        r = d().feed(_frame(2, b"aa") + _frame(3, b"bb"))
        return r == [{"type": 2, "payload": b"aa"}, {"type": 3, "payload": b"bb"}]

    def split_magic():
        dec = d()
        a = dec.feed(b"\xAA")
        b = dec.feed(b"\x55" + _frame(4, b"zz")[2:])
        return a == [] and b == [{"type": 4, "payload": b"zz"}]

    def byte_at_a_time():
        dec = d()
        stream = _frame(5, b"hello") + _frame(6, b"") + _frame(7, b"\x00\x01")
        got = []
        for i in range(len(stream)):
            got.extend(dec.feed(stream[i:i + 1]))
        return got == [{"type": 5, "payload": b"hello"},
                       {"type": 6, "payload": b""},
                       {"type": 7, "payload": b"\x00\x01"}]

    def garbage_prefix():
        return d().feed(b"\x00\x11\x22\x33" + _frame(8, b"ok")) == [{"type": 8, "payload": b"ok"}]

    def bad_crc_then_good():
        bad = bytearray(_frame(9, b"bad"))
        bad[-1] ^= 0xFF
        return d().feed(bytes(bad) + _frame(10, b"good")) == [{"type": 10, "payload": b"good"}]

    def oversized_resync():
        junk = b"\xAA\x55\x01" + (5000).to_bytes(2, "big") + b"xxxx"
        return d().feed(junk + _frame(11, b"tail")) == [{"type": 11, "payload": b"tail"}]

    def incomplete_then_rest():
        f = _frame(12, b"splitpayload")
        dec = d()
        a = dec.feed(f[:6])
        b = dec.feed(f[6:])
        return a == [] and b == [{"type": 12, "payload": b"splitpayload"}]

    def type_255():
        return d().feed(_frame(255, b"x")) == [{"type": 255, "payload": b"x"}]

    def no_exception_on_junk():
        dec = d()
        for _ in range(20):
            dec.feed(b"\x01\x02\x03\xAA\x04")
        r = dec.feed(bytes(range(256)))
        return isinstance(r, list)

    def zeros_payload():
        return d().feed(_frame(13, b"\x00" * 10)) == [{"type": 13, "payload": b"\x00" * 10}]

    return [
        ("one", one), ("empty_payload", empty_payload), ("two_one_chunk", two_one_chunk),
        ("split_magic", split_magic), ("byte_at_a_time", byte_at_a_time),
        ("garbage_prefix", garbage_prefix), ("bad_crc_then_good", bad_crc_then_good),
        ("oversized_resync", oversized_resync), ("incomplete_then_rest", incomplete_then_rest),
        ("type_255", type_255), ("no_exception_on_junk", no_exception_on_junk),
        ("zeros_payload", zeros_payload),
    ]
'''

# ------------------------------------------------------------- task 2: tokens

TOKENS_REF = r'''
import threading
import time


class TokenBucket:
    def __init__(self, rate, capacity, clock=None):
        rate = float(rate)
        capacity = float(capacity)
        if rate <= 0:
            raise ValueError('rate must be positive')
        if capacity <= 0:
            raise ValueError('capacity must be positive')
        self.rate = rate
        self.capacity = capacity
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._tokens = capacity
        self._last = self._clock()

    def _refill_locked(self):
        now = self._clock()
        delta = now - self._last
        if delta > 0:
            self._tokens = min(self.capacity, self._tokens + delta * self.rate)
            self._last = now

    def available(self):
        with self._lock:
            self._refill_locked()
            return self._tokens

    def try_acquire(self, tokens=1.0):
        tokens = float(tokens)
        if tokens <= 0:
            raise ValueError('tokens must be positive')
        if tokens > self.capacity:
            raise ValueError('tokens exceed capacity')
        with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
'''

TOKENS_BROKEN = TOKENS_REF.replace(
    "            self._tokens = min(self.capacity, self._tokens + delta * self.rate)",
    "            self._tokens = self._tokens + delta * self.rate")

TOKENS_TESTS = r'''
import threading


class Clock:
    def __init__(self, t=1000.0):
        self.t = float(t)

    def __call__(self):
        return self.t


def run(m):
    def starts_full():
        b = m.TokenBucket(1.0, 10.0, Clock())
        return abs(b.available() - 10.0) < 1e-9

    def acquire_true():
        b = m.TokenBucket(1.0, 10.0, Clock())
        return b.try_acquire() is True and abs(b.available() - 9.0) < 1e-9

    def acquire_false():
        b = m.TokenBucket(1.0, 1.0, Clock())
        b.try_acquire()
        return b.try_acquire() is False

    def refill_over_time():
        c = Clock()
        b = m.TokenBucket(5.0, 100.0, c)
        for _ in range(100):
            b.try_acquire()
        c.t += 10.0
        return abs(b.available() - 50.0) < 1e-9

    def clamp():
        c = Clock()
        b = m.TokenBucket(5.0, 20.0, c)
        c.t += 1000.0
        return abs(b.available() - 20.0) < 1e-9

    def rejects_bad_args():
        b = m.TokenBucket(1.0, 10.0, Clock())
        ok = 0
        for arg in (0, -1, 10.5):
            try:
                b.try_acquire(arg)
            except ValueError:
                ok += 1
        return ok == 3

    def frozen_threads():
        b = m.TokenBucket(1e-9, 100.0, Clock())
        results = []
        barrier = threading.Barrier(8)

        def worker():
            local = 0
            barrier.wait()
            for _ in range(100):
                if b.try_acquire():
                    local += 1
            results.append(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return sum(results) == 100

    def fractional_rate():
        c = Clock()
        b = m.TokenBucket(0.5, 100.0, c)
        for _ in range(100):
            b.try_acquire()
        c.t += 3.0
        return abs(b.available() - 1.5) < 1e-9

    def never_above_capacity():
        c = Clock()
        b = m.TokenBucket(1000.0, 7.0, c)
        c.t += 5.0
        return b.available() <= 7.0 + 1e-9

    def partial_tokens():
        b = m.TokenBucket(1.0, 10.0, Clock())
        return b.try_acquire(2.5) is True and abs(b.available() - 7.5) < 1e-9

    def no_double_spend():
        c = Clock()
        b = m.TokenBucket(1.0, 3.0, c)
        spent = 0
        while b.try_acquire(1.0):
            spent += 1
        return spent == 3

    return [
        ("starts_full", starts_full), ("acquire_true", acquire_true),
        ("acquire_false", acquire_false), ("refill_over_time", refill_over_time),
        ("clamp", clamp), ("rejects_bad_args", rejects_bad_args),
        ("frozen_threads", frozen_threads), ("fractional_rate", fractional_rate),
        ("never_above_capacity", never_above_capacity), ("partial_tokens", partial_tokens),
        ("no_double_spend", no_double_spend),
    ]
'''

# ------------------------------------------------------------- task 3: legacy

LEGACY_HARD = '''"""Корзина заказов. Модуль в проде два года, менять поведение нельзя."""

_SEP = "-"


def normalize(text, sep=None):
    """Приводит имя к виду slug: обрезает края, нижний регистр, пробелы в разделитель."""
    if sep is None:
        sep = _SEP
    out = []
    for ch in text.strip():
        if ch.isspace():
            if out and out[-1] != sep:
                out.append(sep)
            continue
        out.append(ch.lower())
    return "".join(out).strip(sep) or "_"


def clip(value, lo, hi):
    """Обрезает value в [lo, hi]. Бросает ValueError, если lo > hi."""
    if lo > hi:
        lo, hi = hi, lo
    return max(lo, min(hi, value))


def score(value):
    """Округляет до копеек по правилам банковского округления."""
    return round(float(value), 2)


def bucket(rows, key="sku"):
    """Считает количество строк по значению поля key."""
    counts = {}
    for row in rows:
        raw = row.get(key)
        label = "?" if raw is None else str(raw)
        counts[label] = counts.get(label, 0) + 1
    return counts


def apply_all(items, fn):
    """Применяет fn ко всем элементам и возвращает список результатов."""
    for i in range(len(items)):
        items[i] = fn(items[i])
    return None
'''

LEGACY_HARD_BROKEN = '''"""Clean rewrite (deliberately breaks the quirks)."""


def normalize(text, sep="-"):
    return sep.join(text.split()).lower().strip(sep) or "_"


def clip(value, lo, hi):
    if lo > hi:
        raise ValueError("lo > hi")
    return max(lo, min(hi, value))


def score(value):
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def bucket(rows, key="sku"):
    counts = {}
    for row in rows:
        counts[row.get(key)] = counts.get(row.get(key), 0) + 1
    return counts


def apply_all(items, fn):
    return [fn(item) for item in items]
'''

LEGACY_HARD_TESTS = r'''
import math


def run(m):
    def norm_basic():
        return m.normalize("  A  B  ") == "a-b"

    def norm_keeps_dots():
        return m.normalize("V 1.2 Beta") == "v-1.2-beta"

    def norm_empty():
        return m.normalize("   ") == "_"

    def norm_custom_sep():
        return m.normalize(" a  b ", sep="_") == "a_b"

    def norm_no_trailing_sep():
        return m.normalize("---a---") == "a"

    def clip_swaps_instead_of_raising():
        return m.clip(5, 10, 0) == 5 and m.clip(-3, 10, 0) == 0

    def clip_basic():
        return m.clip(99, 0, 10) == 10 and m.clip(-1, 0, 10) == 0

    def score_bankers():
        return m.score(0.125) == 0.12 and m.score(0.375) == 0.38 and m.score(2.675) == 2.67

    def score_returns_float():
        return isinstance(m.score(10), float) and m.score(10) == 10.0

    def score_negative_zero():
        v = m.score(-0.001)
        return v == 0.0 and math.copysign(1.0, v) < 0

    def bucket_stringifies():
        rows = [{"sku": 1}, {"sku": "1"}, {"sku": 2}]
        return m.bucket(rows) == {"1": 2, "2": 1}

    def bucket_missing():
        return m.bucket([{}, {"sku": None}]) == {"?": 2}

    def apply_all_mutates_and_returns_none():
        items = [1, 2, 3]
        out = m.apply_all(items, lambda x: x * 2)
        return out is None and items == [2, 4, 6]

    def apply_all_same_object():
        items = ["a"]
        m.apply_all(items, str.upper)
        return items[0] == "A" and len(items) == 1

    return [
        ("norm_basic", norm_basic), ("norm_keeps_dots", norm_keeps_dots),
        ("norm_empty", norm_empty), ("norm_custom_sep", norm_custom_sep),
        ("norm_no_trailing_sep", norm_no_trailing_sep),
        ("clip_swaps_instead_of_raising", clip_swaps_instead_of_raising),
        ("clip_basic", clip_basic), ("score_bankers", score_bankers),
        ("score_returns_float", score_returns_float),
        ("score_negative_zero", score_negative_zero),
        ("bucket_stringifies", bucket_stringifies), ("bucket_missing", bucket_missing),
        ("apply_all_mutates_and_returns_none", apply_all_mutates_and_returns_none),
        ("apply_all_same_object", apply_all_same_object),
    ]
'''

# --------------------------------------------------------------- task 4: eval

EVAL_REF = r'''
class _Parser:
    def __init__(self, text):
        self.s = text
        self.i = 0

    def skip(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def peek(self):
        self.skip()
        return self.s[self.i] if self.i < len(self.s) else ''

    def expr(self):
        value = self.term()
        while True:
            c = self.peek()
            if c == '+':
                self.i += 1
                value = value + self.term()
            elif c == '-':
                self.i += 1
                value = value - self.term()
            else:
                return value

    def term(self):
        value = self.unary()
        while True:
            c = self.peek()
            if c == '*':
                self.i += 1
                value = value * self.unary()
            elif c == '/':
                self.i += 1
                divisor = self.unary()
                if divisor == 0:
                    raise ZeroDivisionError('division by zero')
                value = value / divisor
            else:
                return value

    def unary(self):
        c = self.peek()
        if c == '-':
            self.i += 1
            return -self.unary()
        if c == '+':
            self.i += 1
            return self.unary()
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == '^':
            self.i += 1
            return base ** self.unary()
        return base

    def atom(self):
        c = self.peek()
        if c == '(':
            self.i += 1
            value = self.expr()
            if self.peek() != ')':
                raise ValueError('missing )')
            self.i += 1
            return value
        start = self.i
        seen_digit = False
        seen_dot = False
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch.isdigit():
                seen_digit = True
                self.i += 1
            elif ch == '.' and not seen_dot:
                seen_dot = True
                self.i += 1
            else:
                break
        if not seen_digit:
            raise ValueError('expected number')
        return float(self.s[start:self.i])


def evaluate(expr):
    if not isinstance(expr, str):
        raise ValueError('expression must be a string')
    parser = _Parser(expr)
    if parser.peek() == '':
        raise ValueError('empty expression')
    value = parser.expr()
    if parser.peek() != '':
        raise ValueError('unexpected token')
    return float(value)
'''

EVAL_BROKEN = EVAL_REF.replace(
    "    def power(self):\n        base = self.atom()\n        if self.peek() == '^':\n            self.i += 1\n            return base ** self.unary()\n        return base",
    "    def power(self):\n        base = self.atom()\n        if self.peek() == '^':\n            self.i += 1\n            return self.atom()\n        return base")

EVAL_TESTS = r'''
def _raises(fn, *a):
    try:
        fn(*a)
    except Exception:
        return True
    return False


def run(m):
    ev = m.evaluate

    def precedence():
        return ev("2+3*4") == 14

    def parens():
        return ev("(2+3)*4") == 20

    def unary_power():
        return ev("-2^2") == -4

    def right_assoc():
        return ev("2^3^2") == 512

    def negative_exponent():
        return abs(ev("2^-1") - 0.5) < 1e-12

    def unary_times():
        return ev("-3*-2") == 6

    def nested_parens():
        return ev("((1+2)*(3+4))/7") == 3

    def floats():
        return ev("0.5 + .25") == 0.75

    def whitespace():
        return ev("  1 +\t2 ") == 3

    def unary_before_paren():
        return ev("-(2+3)*2") == -10

    def division_float():
        return abs(ev("1/3") - (1 / 3)) < 1e-12

    def zero_div():
        try:
            ev("1/(2-2)")
        except ZeroDivisionError:
            return True
        return False

    def syntax_errors():
        bad = ["2+", "(2", "2)", "abc", "", "  ", "1 2", "*3", "2^^3", "2+."]
        return all(_raises(ev, s) for s in bad)

    def returns_float():
        return isinstance(ev("2"), float) and ev("2") == 2.0

    return [
        ("precedence", precedence), ("parens", parens), ("unary_power", unary_power),
        ("right_assoc", right_assoc), ("negative_exponent", negative_exponent),
        ("unary_times", unary_times), ("nested_parens", nested_parens),
        ("floats", floats), ("whitespace", whitespace),
        ("unary_before_paren", unary_before_paren), ("division_float", division_float),
        ("zero_div", zero_div), ("syntax_errors", syntax_errors),
        ("returns_float", returns_float),
    ]
'''

TASKS = {
    'frames': {
        'prompt': '''Реализуй на Python 3.12 инкрементальный декодер бинарных кадров.

Протокол кадра:
  0xAA 0x55 | type (1 байт) | length (2 байта big-endian) | payload (length байт) | crc16 (2 байта big-endian)

- crc16 = CRC-16/CCITT-FALSE (полином 0x1021, init 0xFFFF) по байтам type||length||payload.
- Максимальная длина payload 4096.

class FrameDecoder:
    def feed(self, data: bytes) -> list[dict]

- feed принимает произвольные куски, порядок сохраняется; каждый вернувшийся кадр
  {"type": int, "payload": bytes}.
- Мусор до магии пропускается, исключений быть не должно.
- Кадр с неверным crc отбрасывается; разбор продолжается после его конца.
- Если length > 4096 — это мусор: продолжай поиск магии со следующего байта после
  первого байта магии.
- Неполный кадр остаётся в буфере до следующих вызовов и не возвращается.

Ответ: только код в одном блоке ```python, без пояснений.''',
        'ref': FRAME_REF,
        'broken': FRAME_BROKEN,
        'broken_must_fail': ['bad_crc_then_good'],
        'tests': FRAME_TESTS,
    },
    'tokens': {
        'prompt': '''Реализуй на Python 3.12 потокобезопасный token bucket.

class TokenBucket:
    def __init__(self, rate: float, capacity: float, clock=None)
    def try_acquire(self, tokens: float = 1.0) -> bool
    def available(self) -> float

- Ведро стартует полным. clock — callable, возвращающий секунды; по умолчанию time.monotonic.
- Пополнение rate токенов в секунду, но не выше capacity; пополнение происходит при
  каждом вызове, по прошедшему времени.
- try_acquire: если доступно >= tokens — списать и вернуть True, иначе False.
- tokens <= 0 или tokens > capacity -> ValueError.
- available() возвращает текущее число токенов (float), никогда больше capacity.
- Все операции потокобезопасны: при 8 потоках суммарно не может быть выдано больше,
  чем позволяет ведро (перепроданных токенов нет, состояние не портится).

Ответ: только код в одном блоке ```python, без пояснений.''',
        'ref': TOKENS_REF,
        'broken': TOKENS_BROKEN,
        'broken_must_fail': ['clamp'],
        'tests': TOKENS_TESTS,
    },
    'legacy': {
        'prompt': '''Ниже модуль, он в проде два года.

```python
{code}```

Перепиши чисто и читаемо. Поведение обязано остаться идентичным, включая все странности
(типы возврата, мутации аргументов, округление, обмен аргументами местами, формат ключей).
Публичные имена и сигнатуры менять нельзя. Докстринги можно поправить под фактическое
поведение. Ответ: только новый файл целиком в одном блоке ```python, без пояснений.''',
        'ref': LEGACY_HARD,
        'broken': LEGACY_HARD_BROKEN,
        'broken_must_fail': ['clip_swaps_instead_of_raising', 'apply_all_mutates_and_returns_none'],
        'tests': LEGACY_HARD_TESTS,
    },
    'eval': {
        'prompt': '''Реализуй на Python 3.12 вычислитель арифметических выражений.

def evaluate(expr: str) -> float

- Операции: + - * / ^, скобки, унарные + и -, десятичные числа (0.5, .25).
- ^ правоассоциативен и приоритетнее унарного минуса слева: -2^2 == -4, 2^3^2 == 512,
  2^-1 == 0.5.
- Пробелы игнорируются.
- Деление на ноль -> ZeroDivisionError.
- Любая синтаксическая ошибка (пустая строка, лишний токен, незакрытая скобка) -> ValueError.
- Возвращается float. Не использовать eval/exec/ast.literal_eval и сторонние парсеры.

Ответ: только код в одном блоке ```python, без пояснений.''',
        'ref': EVAL_REF,
        'broken': EVAL_BROKEN,
        'broken_must_fail': ['right_assoc'],
        'tests': EVAL_TESTS,
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
        'x-opencode-session': 'hard-bench-0000-0000-0000-000000000000',
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


def grade(name, task, source, workdir):
    outdir = os.path.join(workdir, 'grade_' + name)
    os.makedirs(outdir, exist_ok=True)
    solution = os.path.join(outdir, 'sol.py')
    with open(solution, 'w', encoding='utf-8') as fh:
        fh.write(source)
    testfile = os.path.join(outdir, 'test.py')
    with open(testfile, 'w', encoding='utf-8') as fh:
        fh.write(HELPERS_HEAD + task['tests'] + HELPERS_TAIL)
    try:
        proc = subprocess.run([sys.executable, testfile, solution],
                              capture_output=True, text=True, timeout=180)
        lines = (proc.stdout or '').strip().splitlines()
        data = json.loads(lines[-1]) if lines else {'import_error': 'no output', 'results': []}
    except subprocess.TimeoutExpired:
        data = {'import_error': 'timeout', 'results': []}
    return data


def selftest(workdir):
    bad = 0
    for name, task in TASKS.items():
        ref = grade(name + '_ref', task, task['ref'], workdir)
        passed = sum(1 for r in ref['results'] if r['ok'])
        total = len(ref['results'])
        ok = passed == total and not ref.get('import_error')
        failed = [r['name'] + (':' + r['err'] if r.get('err') else '')
                  for r in ref['results'] if not r['ok']]
        print(f'{name:8s} ref {passed}/{total} {"OK" if ok else "FAIL " + str(failed)}')
        bad += 0 if ok else 1

        br = grade(name + '_broken', task, task['broken'], workdir)
        fails = [r['name'] for r in br['results'] if not r['ok']]
        must = task['broken_must_fail']
        caught = all(m in fails for m in must)
        print(f'{name:8s} broken failed {len(fails)}/{len(br["results"])} '
              f'{"OK (caught)" if caught else "MISS: expected " + str(must)}')
        bad += 0 if caught else 1
    print('SELFTEST', 'PASS' if bad == 0 else f'FAIL ({bad})')
    return bad


def run_one(slug, model, name, task, workdir):
    code_or = task.get('ref') if '{code}' in task['prompt'] else None
    prompt = task['prompt'].format(code=code_or) if '{code}' in task['prompt'] else task['prompt']
    try:
        text, usage, sec = call(model, prompt)
    except Exception as exc:
        detail = exc.read()[:300].decode('utf-8', 'ignore') if hasattr(exc, 'read') else ''
        return {'model': slug, 'task': name, 'error': f'{type(exc).__name__}: {exc} {detail}'}

    outdir = os.path.join(workdir, slug)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, name + '.py'), 'w', encoding='utf-8') as fh:
        fh.write(extract(text))

    data = grade(f'{slug}_{name}', task, extract(text), workdir)
    details = usage.get('completion_tokens_details') or {}
    return {
        'model': slug, 'task': name,
        'passed': sum(1 for r in data['results'] if r['ok']),
        'total': len(data['results']),
        'import_error': data.get('import_error'),
        'fails': [r['name'] for r in data['results'] if not r['ok']],
        'tokens': usage.get('total_tokens'),
        'prompt_tokens': usage.get('prompt_tokens'),
        'completion_tokens': usage.get('completion_tokens'),
        'reasoning': details.get('reasoning_tokens'),
        'sec': round(sec, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', default=','.join(TASKS))
    ap.add_argument('--models', default='sol-6.1,terra')
    ap.add_argument('--out', default='/workspace/bench/hard.jsonl')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    workdir = os.path.dirname(args.out) or '.'
    os.makedirs(workdir, exist_ok=True)

    if args.selftest:
        sys.exit(1 if selftest(workdir) else 0)

    tasks = [t.strip() for t in args.task.split(',') if t.strip()]
    wanted = {m.strip() for m in args.models.split(',') if m.strip()}
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
