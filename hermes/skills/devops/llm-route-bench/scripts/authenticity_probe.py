"""Is a resold model route really the model it claims? Paired probe.

Compares a suspect route (reseller/proxy) against the same model on a trusted route
plus cheap control models. Tasks are deliberately hard, exact-answer maths with the
ground truth COMPUTED IN THIS FILE, and code tasks graded by executing hidden tests —
never by reading the answer.

Example:
  python3 authenticity_probe.py \
      --suspect gemini-4-argon --suspect-url https://api.tokenator.top/v1 --suspect-key-env TOK_KEY \
      --trusted google/gemini-4-argon \
      --control anthropic/claude-haiku-5.5 --control service.deepseek/deepseek-v4.1-flash

Reads the gateway master key from /home/ai_service/ai-stack/ai/.env when --trusted is a
LiteLLM group; never prints keys. Refuses frontier names without --allow-expensive.
"""
import argparse, json, os, re, statistics, subprocess, sys, tempfile, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

EXPENSIVE = ('opus', 'gpt-6', 'sonnet', 'sol', 'terra')


# ---------- ground truth, computed not hardcoded ----------
def _trailing_zeros(n):
    z, p = 0, 5
    while p <= n:
        z += n // p
        p *= 5
    return z


def _largest_prime_factor(n):
    f, d = 1, 3
    while d * d <= n:
        while n % d == 0:
            f, n = d, n // d
        d += 2
    return max(f, n)


def build_tasks():
    n100 = next(n for n in range(1, 5000) if _trailing_zeros(n) == 100)
    maths = [
        ('zeros200', 'How many trailing zeros does 200! have? Number only.',
         str(_trailing_zeros(200))),
        ('smallest_n', 'Find the smallest positive integer n such that n! has exactly 100 '
                       'trailing zeros. Number only.', str(n100)),
        ('mod13', 'What is the remainder when 2^1000 is divided by 13? Number only.',
         str(pow(2, 1000, 13))),
        ('pairs', 'How many ordered pairs of positive integers (a,b) satisfy 1/a + 1/b = 1/6? '
                  'Number only.', '9'),
        ('coprime', 'How many integers from 1 to 1000 inclusive are divisible by none of 2, 3, 5? '
                    'Number only.',
         str(sum(1 for n in range(1, 1001) if n % 2 and n % 3 and n % 5))),
        ('pp_factor', 'What is the largest prime factor of 2^32 - 1? Number only.',
         str(_largest_prime_factor(2 ** 32 - 1))),
    ]
    codes = [
        ('nth_prime', 'Write a Python function `f(n)` that returns the n-th prime (1-indexed). '
                      'Reply with code only, no prose.',
         'assert f(1)==2 and f(10)==29 and f(100)==541'),
        ('merge', 'Write a Python function `merge(intervals)` that merges overlapping intervals '
                  'and returns them sorted. Reply with code only, no prose.',
         'assert merge([[1,3],[2,6],[8,10],[15,18]])==[[1,6],[8,10],[15,18]]\n'
         'assert merge([[1,4],[4,5]])==[[1,5]]\nassert merge([])==[]'),
        ('rle', 'Write a Python function `rle(s)` run-length encoding: "aaabbc" -> "a3b2c1". '
                'Reply with code only, no prose.',
         'assert rle("aaabbc")=="a3b2c1"\nassert rle("")==""\nassert rle("x")=="x1"'),
    ]
    return maths, codes


def post(url, key, model, messages, max_tokens=800):
    body = {'model': model, 'messages': messages, 'max_tokens': max_tokens, 'temperature': 0}
    req = urllib.request.Request(url.rstrip('/') + '/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + key,
                                          'Content-Type': 'application/json'})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            d = json.loads(r.read())
            return dict(ok=True, answer=d['choices'][0]['message'].get('content') or '',
                        usage=d.get('usage') or {}, t=time.time() - t)
    except urllib.error.HTTPError as e:
        return dict(ok=False, answer='', err=f'HTTP {e.code}',
                    body=e.read()[:160].decode('utf8', 'ignore'), t=time.time() - t)
    except Exception as e:
        return dict(ok=False, answer='', err=str(e)[:80], t=time.time() - t)


def numbers(text):
    return {x.replace(',', '.') for x in re.findall(r'-?\d+(?:[.,]\d+)?',
                                                    (text or '').replace('**', ''))}


def run_code(answer, test):
    code = answer
    m = re.search(r'```(?:python)?\n(.*?)```', code, re.S)
    if m:
        code = m.group(1)
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fh:
        fh.write(code + '\n\n' + test + '\nprint("PASS")\n')
        path = fh.name
    try:
        p = subprocess.run([sys.executable, path], capture_output=True, timeout=20, text=True)
        return int(p.returncode == 0 and 'PASS' in p.stdout)
    except Exception:
        return 0
    finally:
        os.unlink(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--suspect', required=True, help='model id on the suspect route')
    ap.add_argument('--suspect-url', required=True)
    ap.add_argument('--suspect-key-env', required=True, help='env var holding the suspect key')
    ap.add_argument('--trusted', required=True, help='same model on a trusted route (LiteLLM group ok)')
    ap.add_argument('--gateway', default='http://127.0.0.1:4000/v1')
    ap.add_argument('--control', action='append', default=[], help='control model on the gateway')
    ap.add_argument('--json', default=None)
    ap.add_argument('--allow-expensive', action='store_true')
    a = ap.parse_args()

    if not a.allow_expensive and any(x in (a.suspect + a.trusted).lower() for x in EXPENSIVE):
        sys.exit('refusing a frontier model without --allow-expensive (owner approval required)')

    mk = os.environ.get('MK') or ''
    if not mk:
        for line in open('/home/ai_service/ai-stack/ai/.env'):
            if line.startswith('LITELLM_MASTER_KEY='):
                mk = line.split('=', 1)[1].strip().strip('"')
    routes = {
        'suspect': (a.suspect_url, os.environ[a.suspect_key_env], a.suspect),
        'trusted': (a.gateway, mk, a.trusted),
    }
    for i, c in enumerate(a.control):
        routes[f'control{i + 1}'] = (a.gateway, mk, c)

    maths, codes = build_tasks()
    print('ground truth:', {n: e for n, _, e in maths})

    def task(job):
        kind, name, prompt, expect = job
        out = {}
        for rname, (url, key, model) in routes.items():
            res = post(url, key, model, [{'role': 'user', 'content': prompt}])
            if res['ok']:
                res['score'] = run_code(res['answer'], expect) if kind == 'code' \
                    else int(expect in numbers(res['answer']))
            out[rname] = res
        return name, out

    jobs = [('math',) + m for m in maths] + [('code',) + c for c in codes]
    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(task, jobs):
            results[name] = out

    print()
    for name, out in results.items():
        cells = [(('x' if not r['ok'] else str(r['score'])).ljust(2) +
                  (r['answer'] if r['ok'] else r.get('err', '')).strip().replace('\n', ' ')[:24].ljust(26))
                 for r in (out[k] for k in routes)]
        print(name.ljust(12), ''.join(cells))
    print()
    for rname in routes:
        ok = [o[rname] for o in results.values() if o[rname]['ok']]
        lat = [o['t'] for o in ok]
        print(f"  {rname:9} {sum(1 for o in ok if o['score'])}/{len(jobs)}"
              + (f"  median {statistics.median(lat):.1f}s" if lat else ''))
    agree = sum(1 for o in results.values() if o['suspect'].get('score') == o['trusted'].get('score'))
    print(f"\n  suspect vs trusted: identical verdict on {agree}/{len(jobs)} tasks")

    png = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ'
           'AAAABJRU5ErkJggg==')
    url, key, model = routes['suspect']
    vis = post(url, key, model, [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'What colour is this image? One word.'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + png}}]}], max_tokens=20)
    print('\n  suspect vision:', repr(vis.get('answer', '')[:40] or vis.get('err')),
          '| reasoning_tokens:',
          (vis.get('usage') or {}).get('completion_tokens_details', {}).get('reasoning_tokens'))

    if a.json:
        json.dump({k: {r: {kk: vv for kk, vv in v.items() if kk != 't'} for r, v in o.items()}
                   for k, o in results.items()}, open(a.json, 'w'), ensure_ascii=False, indent=1)
        print('  saved ->', a.json)


if __name__ == '__main__':
    main()
