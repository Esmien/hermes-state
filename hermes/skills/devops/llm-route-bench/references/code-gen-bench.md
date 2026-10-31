# Code-generation bench: hidden tests, not opinions

Purpose: answer «какая модель лучше пишет код / пусть потягаются» with numbers the owner
can check. The model writes code; the code is executed; the score is how many hidden tests
passed on the first attempt.

## Model-name resolution

Open WebUI stores models with a namespace prefix (`chat.<model>`); LiteLLM knows them
**without** it. Resolving `chat.openai/gpt-6.1-sol` against the gateway gives 400.

- OWUI `chat.deepseek/deepseek-v4.1-flash` → `deepseek/deepseek-v4.1-flash`
- A model can be listed in the OWUI UI and be absent from LiteLLM — then every call is 400
  `Invalid model name`. Check `/model/info` before adding the model to the bench; a dead UI
  entry is a finding to report, not a bench failure to hide.
- Deployments on OpenCode Go need `x-opencode-session: <any-uuid>` on the request, even on
  `/v1/chat/completions`; without it the answer is a 400 that looks like a wrong model name.

## Harness

Run **inside** the sandbox container (`open-terminal-sandbox` has python3 and network to
`litellm:4000`), not on the host: the model's own test run should not touch the VPS host.

1. `POST http://litellm:4000/v1/chat/completions`, `Authorization: Bearer $LITELLM_MASTER_KEY`
   (read from `ai/.env` on the host and passed with `docker exec -e`, never printed).
2. Body: one user message, `reasoning_effort: "high"`, `stream: false`, timeout 900-1800 s.
3. Extract the **last** ```python block; if there is none, take the whole text — a model that
   answered in prose then fails every test, which is the correct outcome.
4. Write the solution to a file, generate a test file that imports it by path
   (`importlib.util.spec_from_file_location`), run it as a subprocess with a timeout, parse a
   JSON line with per-test pass/fail.
5. Append one JSONL row per (model, task): score, failed test names, tokens, reasoning tokens,
   seconds. Print the same row to stdout for progress.

**Validate the harness before spending calls:** run the reference solution (must be 100%) and
a deliberately broken one (must fail the specific tests) through the same generated test file.
A harness bug looks exactly like eleven models writing garbage.

## Task ladder

| Task | What it measures | Tests |
|---|---|---|
| `truncate_utf8` | byte-accurate slicing, boundary conditions | 10 |
| `parse_size` | spec parsing, unit table, error paths | 11 |
| `csv_line` (RFC 4180 subset) | state machine, quoting edge cases | 12 |
| `expr_eval` | precedence, unary minus, error taxonomy | 15 |
| `legacy_refactor` | preserving quirks and the public API | 15 |
| `framing` (binary protocol + CRC16) | streaming, resync, chunk boundaries | 11 |
| `needle` (bug in a 250-470 line file) | long-context attention | 10 |

First four are the easy tier: every model in the stack scores 100%. Keep them as a smoke
test, never as a ranking.

## Grading gotchas

- Patch `time.sleep` inside the tests before calling the code under test. A planted unit bug
  makes the model sleep 200 seconds and the whole test file hits the subprocess timeout, which
  reads as «no output» instead of «bug found».
- Error-path tests need type-specific helpers (`_raises` for ValueError, separate ones for
  ZeroDivisionError and KeyError); a generic `except Exception` scores wrong behaviour as pass.
- Behavioural-preservation tests must call functions **by name**: renaming a public function is
  the most common regression and only a name-level call catches it.
- Test stability before trusting a difference: rerun a failing model once. A single failed
  test out of 44 is noise; a failed concurrency test is a real defect.

## Cross-review protocol

To measure review rather than generation: take the solutions produced by the models, strip
identifiers, give **the same anonymized set to every reviewer** (A/B/C/D), and require a
strict per-letter answer format so replies can be graded mechanically. Same prompt size for
all reviewers is part of the fairness.

- Include one empty-input control: a reviewer that verdicts «багов нет» on an empty prompt is
  unsafe for production review regardless of its score.
- Grade by whether the planted defect is named, not by the number of findings: plausible
  style findings are cheap, the arithmetic defect is the one that matters.

## Baseline on this stack (re-run before trusting)

Tier 1, пять задач / 59 тестов: Haiku 59/59 (6.9 s), Muse Spark 59/59 (20 s, 13.6k reasoning),
MiMo 58/59 (4.4k токенов — самый экономный), Luna 58/59 (4.6 s — самая быстрая),
GLM 38/38 на трёх задачах (в первом раунде без заголовка сессии), **DeepSeek 55/59** —
единственный, кто переименовал публичную функцию (`total` → `to`) при «чистом переписывании».

Tier 2, пять задач / 48 тестов: Terra, Sol, Astra — 46/48, Argon 45/48 (упал тест на
конкуренции). Все провалили одно и то же: не нашли несовпадение единиц в `_backoff` в файле
на 472 строки. Terra 7.7 s против Sol 22 s и Astra 30 s при равном счёте.

Что это значит для ролей: Terra — дефолт (втрое быстрее и вдвое дешевле при том же счёте),
Sol — эскалация после двух неудач, DeepSeek — код с обязательной проверкой имён и сигнатур,
Muse Spark — фоновый объём (плоская подписка OpenCode, 20 s никого не волнуют).

Cross-review: 0 из 16 пар «ревьюер × файл» назвали заложенный дефект единиц; на пустом
промпте Astra и Terra выдали «багов нет», Sol честно ответил «пришлите код».
