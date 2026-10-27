#!/usr/bin/env python3
"""A/B benchmark of LiteLLM routes: identical harness, deterministic grading.

Usage:
    python3 ab_bench.py                                  # default cheap pair
    python3 ab_bench.py --probe deepseek/deepseek-v4.1-flash
    python3 ab_bench.py --runs 2 deepseek/deepseek-v4.1-flash anthropic/claude-haiku-5.5

Reads LITELLM_MASTER_KEY from the stack .env; never prints it.
Prices come from /model/info, so the cost columns stay honest.
"""
import json, re, sys, time, statistics, urllib.request

ENV = "/home/ai_service/ai-stack/ai/.env"
BASE = "http://127.0.0.1:4000"
KEY = [l.split("=", 1)[1].strip().strip('"').strip("'")
       for l in open(ENV, encoding="utf-8", errors="ignore")
       if l.startswith("LITELLM_MASTER_KEY=")][0]
HDR = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def _req(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=HDR)
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read())


def prices():
    out = {}
    try:
        for it in _req("/model/info")["data"]:
            p = it.get("litellm_params") or {}
            i, o = p.get("input_cost_per_token"), p.get("output_cost_per_token")
            if i is not None and o is not None:
                out.setdefault(it["model_name"], (i * 1e6, o * 1e6))
    except Exception:
        pass
    return out


def chat(model, messages, tools=None, max_tokens=None):
    body = {"model": model, "messages": messages, "temperature": 0}
    if tools:
        body["tools"] = tools
    if max_tokens:
        body["max_tokens"] = max_tokens
    t0 = time.time()
    d = _req("/v1/chat/completions", body)
    return d, time.time() - t0, d.get("usage") or {}


TOOLS = [
    {"type": "function", "function": {
        "name": "get_gold_price",
        "description": "Курс золота ЦБ РФ за дату, рублей за грамм чистого металла",
        "parameters": {"type": "object", "properties": {"date": {"type": "string"}},
                       "required": ["date"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "get_pawn_rate",
        "description": "Ставка ломбарда за грамм изделия",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"},
            "fineness": {"type": "integer", "enum": [375, 500, 585, 750, 999]}},
            "required": ["city", "fineness"], "additionalProperties": False}}},
]


def tool_result(name, args):
    if name == "get_gold_price":
        return {"rub_per_gram": 10385.78} if args.get("date") == "2026-10-27" else {"error": "no data"}
    if name == "get_pawn_rate":
        return {"city": args.get("city"), "fineness": args.get("fineness"), "rub_per_gram": 6200}
    return {"error": "unknown tool"}


def agent(model, messages, tools=None, max_turns=4):
    msgs = list(messages)
    t0 = time.time()
    tin = tout = 0
    calls, errs, turns, text = [], [], [], ""
    for _ in range(max_turns):
        try:
            d, dt, u = chat(model, msgs, tools)
        except Exception as e:
            errs.append(f"http:{e}")
            break
        tin += u.get("prompt_tokens", 0)
        tout += u.get("completion_tokens", 0)
        msg = d["choices"][0]["message"]
        tcs = msg.get("tool_calls") or []
        turns.append(len(tcs))
        if not tcs:
            text = msg.get("content") or ""
            break
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
        for tc in tcs:
            name = tc["function"]["name"]
            raw = tc["function"].get("arguments") or ""
            try:
                args = json.loads(raw)
                ok = isinstance(args, dict)
            except Exception:
                args, ok = {}, False
                errs.append("bad_json")
            calls.append((name, ok, args))
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", "x"),
                         "content": json.dumps(tool_result(name, args), ensure_ascii=False)})
    return text, {"lat": time.time() - t0, "in": tin, "out": tout,
                  "calls": calls, "errs": errs, "turns": turns}


N = lambda s: re.sub(r"[\s\u00a0\u202f]", "", s)


def t_tool_call(m):
    t, x = agent(m, [{"role": "user", "content":
        "Узнай курс золота ЦБ РФ на 2026-10-27. Ответь одной строкой: сколько рублей за грамм."}], TOOLS)
    ok = (len(x["calls"]) == 1 and x["calls"][0][0] == "get_gold_price" and x["calls"][0][1]
          and x["calls"][0][2].get("date") == "2026-10-27" and "10385" in N(t))
    return ok, x


def t_math(m):
    q = ("Клиент сдаёт 3,5 г золота 585 в Краснодаре. Ставка скупки = ставка ломбарда минус 12%. "
         "Узнай ставку для 585 в Краснодаре и назови итог за 3,5 г в рублях.")
    t, x = agent(m, [{"role": "user", "content": q}], TOOLS)
    ok = any(c[0] == "get_pawn_rate" and c[1] for c in x["calls"]) and "19096" in N(t)
    return ok, x


def t_json(m):
    q = ('Верни строго JSON-объект с ключами: city (строка), rates (массив из трёх объектов '
         'с ключами fineness и rub), total (число). Значения: Краснодар, 585=6200, 750=7950, '
         '999=10600, total — сумма трёх ставок. Без markdown.')
    t, x = agent(m, [{"role": "user", "content": q}])
    try:
        d = json.loads(t.strip().strip("`"))
        ok = (d["city"] == "Краснодар" and len(d["rates"]) == 3 and d["total"] == 24750
              and {r["fineness"] for r in d["rates"]} == {585, 750, 999})
    except Exception:
        ok = False
    return ok, x


def t_words(m):
    q = ("Объясни, зачем в sshd_config нужен PasswordAuthentication no. "
         "Ровно 40 слов. Без списков, без markdown.")
    t, x = agent(m, [{"role": "user", "content": q}])
    return len(re.findall(r"\S+", t.strip())) == 40, x


def t_negative(m):
    q = ("Дай 3 совета, как проверить подлинность пробы на ювелирном изделии. Строго: каждый пункт — "
         "одна строка, максимум 12 слов, нумерация 1. 2. 3. Слово «золото»/«золотой» не использовать.")
    t, x = agent(m, [{"role": "user", "content": q}])
    lines = [l for l in t.strip().split("\n") if re.match(r"^\s*[123][.)]", l)]
    ok = (len(lines) == 3 and all(len(re.sub(r"^\s*[123][.)]\s*", "", l).split()) <= 12 for l in lines)
          and "золот" not in t.lower())
    return ok, x


def t_parallel(m):
    q = ("Узнай одним ходом две вещи: цену ЦБ на 2026-10-27 и ставку ломбарда 585 в Краснодаре. "
         "Оба вызова — в одном ответе. Потом посчитай, на сколько процентов ставка ниже курса, округли до целого.")
    t, x = agent(m, [{"role": "user", "content": q}], TOOLS)
    return (x["turns"][:1] == [2] and "40" in t and "10385" in N(t)), x


def t_args(m):
    q = "Сдаю в ломбард «Краснодар, Красная 62» изделие — проба 585-я. Узнай ставку за грамм и назови её."
    t, x = agent(m, [{"role": "user", "content": q}], TOOLS)
    ok = any(c[0] == "get_pawn_rate" and c[1] and c[2].get("fineness") == 585 for c in x["calls"]) \
         and "6200" in N(t)
    return ok, x


def t_long(m):
    fill = "Запись реестра без значимых данных, строка %d. "
    doc = "".join(fill % i for i in range(120)) + \
          " Тариф «Базовый»: 6200 ₽/г. Тариф «Индивидуальный»: 6955 ₽/г. Тариф «Максимальный»: 7300 ₽/г." + \
          "".join(fill % i for i in range(120, 260))
    q = ("Документ ниже. Сколько стоит грамм по тарифу, который дороже «Базового», но дешевле "
         "«Максимального»? Ответь числом.\n\n" + doc)
    t, x = agent(m, [{"role": "user", "content": q}])
    return ("6955" in N(t) or "6 955" in t), x


TASKS = [("tool_call", t_tool_call), ("math", t_math), ("strict_json", t_json),
         ("word_limit", t_words), ("neg_constraint", t_negative), ("parallel_tools", t_parallel),
         ("tool_args", t_args), ("long_distractor", t_long)]

DEFAULT = ["deepseek/deepseek-v4.1-flash", "anthropic/claude-haiku-5.5"]


def probe(models):
    print("--- hidden-prompt probe (prompt_tokens for 'скажи ок') ---")
    for m in models:
        toks = []
        for _ in range(3):
            try:
                d, _, u = chat(m, [{"role": "user", "content": "Скажи одно слово: ок"}], max_tokens=5)
                toks.append(u.get("prompt_tokens"))
            except Exception as e:
                toks.append(f"ERR:{str(e)[:30]}")
        ints = [t for t in toks if isinstance(t, int)]
        base = min(ints) if ints else None
        flag = "INJECTED" if isinstance(base, int) and base > 200 else "clean"
        print(f"  {m:44s} {toks}  {flag}")


def cheap_guard(models, allowed):
    EXPENSIVE = ("opus", "gpt-6", "sonnet")
    if any(a in m for m in models for a in EXPENSIVE) and not allowed:
        sys.exit("Стоп: в списке дорогая модель. Запускай с --allow-expensive, если это осознанно.")


def main():
    args = sys.argv[1:]
    runs = 1
    if "--runs" in args:
        i = args.index("--runs")
        runs = int(args[i + 1])
        del args[i:i + 2]
    do_probe = "--probe" in args
    if do_probe:
        args.remove("--probe")
    allow_expensive = "--allow-expensive" in args
    if allow_expensive:
        args.remove("--allow-expensive")
    models = args or DEFAULT
    cheap_guard(models, allow_expensive)
    PR = prices()
    if do_probe:
        probe(models)
        print()

    res = {}
    for model in models:
        pin, pout = PR.get(model, (0.0, 0.0))
        if model not in PR:
            print(f"! {model}: нет цены в /model/info, cost = 0")
        rows = []
        for _ in range(runs):
            for name, fn in TASKS:
                try:
                    ok, x = fn(model)
                except Exception as e:
                    ok, x = False, {"lat": 0, "in": 0, "out": 0, "calls": [], "errs": [str(e)], "turns": []}
                cost = x["in"] / 1e6 * pin + x["out"] / 1e6 * pout
                rows.append({"task": name, "ok": bool(ok), "lat": x["lat"], "cost": cost,
                             "in": x["in"], "out": x["out"], "turns": x["turns"], "errs": x["errs"]})
                print(f"  {model:34s} {name:15s} {'PASS' if ok else 'FAIL'} {x['lat']:6.1f}s "
                      f"in={x['in']:6d} out={x['out']:5d} ${cost:.5f} turns={x['turns']} {x['errs']}", flush=True)
        res[model] = rows

    print("\n=== SUMMARY ===")
    for model, rows in res.items():
        ok = sum(r["ok"] for r in rows)
        n = len(rows)
        cost = sum(r["cost"] for r in rows)
        print(f"{model:34s} {ok}/{n} ({100*ok/n:.0f}%)  median {statistics.median(r['lat'] for r in rows):5.1f}s  "
              f"${cost:.4f} total  ${cost/max(ok,1):.5f}/успех")
        for t in sorted({r["task"] for r in rows}):
            st = [r["ok"] for r in rows if r["task"] == t]
            if not all(st):
                print(f"    FAIL {t}")
    json.dump(res, open("/root/.hermes/cache/scratch/ab_last.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
