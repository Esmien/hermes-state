#!/usr/bin/env python3
"""A/B benchmark for LiteLLM routes: hidden-prompt probe + discriminating task set.

Usage: model-route-bench.py [model ...]   (default: a few ids from /v1/models)
Output: per-call lines + summary (pass rate, median latency, $/task, $/success).

Why it exists: "model X is worse than Y" is usually a route problem — a proxy that
injects its own system prompt shows up as thousands of prompt_tokens on a 19-token
request, degrades instruction-following and inflates cost. Probe first, then grade.
"""
import json, re, statistics, sys, time, urllib.request

ENV = "/home/ai_service/ai-stack/ai/.env"
BASE = "http://127.0.0.1:4000"
RUNS = 2


def key():
    for line in open(ENV, encoding="utf-8", errors="ignore"):
        if line.startswith("LITELLM_MASTER_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("LITELLM_MASTER_KEY not found")


K = key()


def api(path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {K}"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def prices():
    out = {}
    for it in api("/model/info").get("data", []):
        p = it.get("litellm_params", {})
        i, o = p.get("input_cost_per_token"), p.get("output_cost_per_token")
        if i is not None and o is not None:
            out.setdefault(it["model_name"], (i * 1e6, o * 1e6))  # $/1M
    return out


def chat(model, messages, tools=None, max_tokens=None):
    body = {"model": model, "messages": messages, "temperature": 0}
    if tools:
        body["tools"] = tools
    if max_tokens:
        body["max_tokens"] = max_tokens
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {K}",
                                          "Content-Type": "application/json"})
    t0 = time.time()
    d = json.loads(urllib.request.urlopen(req, timeout=240).read())
    return d, time.time() - t0, d.get("usage") or {}


TOOLS = [
    {"type": "function", "function": {
        "name": "get_pawn_rate",
        "description": "Ставка ломбарда за грамм изделия",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"},
                                      "fineness": {"type": "integer",
                                                   "enum": [375, 500, 585, 750, 999]}},
                       "required": ["city", "fineness"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "get_gold_price",
        "description": "Курс золота ЦБ РФ, рублей за грамм чистого металла",
        "parameters": {"type": "object", "properties": {"date": {"type": "string"}},
                       "required": ["date"], "additionalProperties": False}}},
]


def tool_result(name, a):
    if name == "get_pawn_rate":
        return {"fineness": a.get("fineness"), "rub_per_gram": 6200}
    return {"rub_per_gram": 10385.78}


def agent(model, messages, tools=None, turns=4):
    msgs, calls, errs, turn_sizes, text = list(messages), [], [], [], ""
    tin = tout = 0
    t0 = time.time()
    for _ in range(turns):
        try:
            d, _, u = chat(model, msgs, tools)
        except Exception as e:
            errs.append(f"http:{e}")
            break
        tin += u.get("prompt_tokens", 0)
        tout += u.get("completion_tokens", 0)
        m = d["choices"][0]["message"]
        tcs = m.get("tool_calls") or []
        turn_sizes.append(len(tcs))
        if not tcs:
            text = m.get("content") or ""
            break
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
        for tc in tcs:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except Exception:
                args = {}
                errs.append("bad_json")
            calls.append((name, args))
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", "x"),
                         "content": json.dumps(tool_result(name, args), ensure_ascii=False)})
    return text, {"lat": time.time() - t0, "in": tin, "out": tout, "calls": calls,
                  "errs": errs, "turns": turn_sizes}


N = lambda s: re.sub(r"[\s\u00a0\u202f]", "", s)


def t_parallel(model):
    q = ("Узнай одним ходом две вещи: цену золота ЦБ на 2026-10-27 и ставку ломбарда 585 "
         "в Краснодаре. Оба вызова — в одном ответе. Потом посчитай, на сколько процентов "
         "ставка ниже курса, округли до целого.")
    txt, m = agent(model, [{"role": "user", "content": q}], tools=TOOLS)
    return (m["turns"][:1] == [2] and "40" in txt and "10385" in N(txt)), m


def t_args(model):
    q = "Сдаю в ломбард «Краснодар, Красная 62» изделие — проба 585-я. Узнай ставку за грамм."
    txt, m = agent(model, [{"role": "user", "content": q}], tools=TOOLS)
    ok = any(c[0] == "get_pawn_rate" and c[1].get("fineness") == 585 for c in m["calls"])
    return (ok and "6200" in N(txt)), m


def t_words(model):
    q = ("Объясни, зачем в sshd_config нужен PasswordAuthentication no. Ровно 40 слов. "
         "Без списков, без markdown.")
    txt, m = agent(model, [{"role": "user", "content": q}])
    return len(re.findall(r"\S+", txt.strip())) == 40, m


def t_json(model):
    q = ('Верни строго JSON-объект с ключами: city (строка), rates (массив из трёх объектов '
         'с ключами fineness и rub), total (число). Значения: Краснодар, 585=6200, 750=7950, '
         '999=10600, total — сумма трёх ставок. Без markdown.')
    txt, m = agent(model, [{"role": "user", "content": q}])
    try:
        d = json.loads(txt.strip().strip("`"))
        ok = (d["city"] == "Краснодар" and d["total"] == 24750
              and len(d["rates"]) == 3)
    except Exception:
        ok = False
    return ok, m


def t_code(model):
    bad = ('def total_weight(items):\n    s = 0\n    for i in items:\n        s += i.weight\n'
           '    return s\n# items: [{"weight": 2.0}, {"weight": 3.5}]')
    txt, m = agent(model, [{"role": "user", "content":
                            "Функция падает на списке словарей. Верни ТОЛЬКО исправленный код без "
                            "markdown:\n" + bad}])
    code = re.sub(r"^python\n", "", txt.strip().strip("`"))
    ns = {}
    try:
        exec(code, ns)
        ok = abs(ns["total_weight"]([{"weight": 2.0}, {"weight": 3.5}]) - 5.5) < 1e-9
    except Exception:
        ok = False
    return ok, m


TASKS = [("parallel_tools", t_parallel), ("dirty_args", t_args),
         ("word_limit_40", t_words), ("json_strict", t_json), ("code_fix", t_code)]


def probe(model, n=4):
    seen = []
    for _ in range(n):
        try:
            _, _, u = chat(model, [{"role": "user", "content": "Скажи одно слово: ок"}], max_tokens=5)
            seen.append(u.get("prompt_tokens"))
        except Exception as e:
            seen.append(f"ERR:{type(e).__name__}")
    return seen


def main():
    models = sys.argv[1:]
    price = prices()
    if not models:
        models = list(price)[:3]
    print("=== hidden-prompt probe (19-token request, prompt_tokens) ===")
    for m in models:
        got = probe(m)
        nums = [x for x in got if isinstance(x, int)]
        flag = "INJECTED" if nums and max(nums) > 500 else "clean"
        print(f"{m:40s} {got}  -> {flag}")
    print("\n=== tasks ===")
    summary = {}
    for m in models:
        rows = []
        pin, pout = price.get(m, (0, 0))
        for _ in range(RUNS):
            for name, fn in TASKS:
                try:
                    ok, r = fn(m)
                except Exception as e:
                    ok, r = False, {"lat": 0, "in": 0, "out": 0, "errs": [str(e)]}
                cost = r["in"] / 1e6 * pin + r["out"] / 1e6 * pout
                rows.append((name, ok, r["lat"], cost))
                print(f"{m:40s} {name:15s} {'PASS' if ok else 'FAIL'} {r['lat']:5.1f}s "
                      f"in={r['in']:6d} out={r['out']:5d} ${cost:.5f} {r['errs']}")
        summary[m] = rows
    print("\n=== SUMMARY ===")
    for m, rows in summary.items():
        ok = sum(r[1] for r in rows)
        cost = sum(r[3] for r in rows)
        print(f"{m:40s} {ok}/{len(rows)}  median {statistics.median(r[2] for r in rows):5.1f}s "
              f"${cost:.4f} total  ${cost / max(ok, 1):.4f}/успех")


if __name__ == "__main__":
    main()
