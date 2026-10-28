#!/usr/bin/env python3
"""E2E прогон пользовательских сценариев музыкального бота lyria (lyria-bot).

Запуск:  python3 scripts/lyria-e2e.py            # все сценарии, ~$0.3, ~10 минут
         python3 scripts/lyria-e2e.py --no-generate   # только бесплатные сценарии

Стенд:
  * апдейты форжатся на локальный webhook (X-Telegram-Bot-Api-Secret-Token из env
    контейнера, в лог не пишется); бот обрабатывает их как настоящие и отвечает
    в реальный чат владельца;
  * проверки — по БД lyria-postgres и логам контейнеров, а не по «прочитанным»
    ответам бота (у бота нет API для чтения своей истории).

Ограничение: у форж-callback_query нет настоящего query_id, поэтому Telegram
отвечает «query is too old» на callback.answer(). Там, где хендлер вызывает
answer() ДО полезной работы («Подтвердить», «Без обогащения», «Оставить как
есть»), шаг выполняется production-функциями бота: save_enriched_prompt +
_build_generation_prompt + запись FSM waiting_for_title.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

OWNER = 214062001
OTHER = 332311799
BOT_ID = 8942340701
CHAT = OWNER
WEBHOOK = "http://127.0.0.1:8000/webhook"
BASE = Path("/root/.hermes/cache/scratch")
OUT = BASE / "lyria_e2e.jsonl"
ART = BASE / "songs"

_uid = 1_100_000_000
_mid = 2_000_000


def cenv(*names: str) -> dict[str, str]:
    out = subprocess.run(["docker", "exec", "lyria-bot", "printenv", *names], capture_output=True, text=True, check=True)
    return dict(zip(names, out.stdout.splitlines()))


SECRETS = cenv("BOT_TOKEN", "WEBHOOK_SECRET", "BOT_ACCESS_KEY")
TOKEN, SECRET, ACCESS_KEY = SECRETS["BOT_TOKEN"], SECRETS["WEBHOOK_SECRET"], SECRETS["BOT_ACCESS_KEY"]


def next_uid() -> int:
    global _uid
    _uid += 1
    return _uid


def next_mid() -> int:
    global _mid
    _mid += 1
    return _mid


def log(step: str, data: object) -> None:
    rec = {"ts": time.strftime("%H:%M:%S"), "step": step, "data": data}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), flush=True)


def sql(query: str) -> str:
    out = subprocess.run(
        ["docker", "exec", "lyria-postgres", "psql", "-U", "lyria", "-d", "lyria", "-tAc", query],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return out.stdout.strip()


def _post_json(url: str, payload: dict, headers: dict | None = None) -> tuple[int, bytes]:
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def post(update: dict) -> int:
    status, _ = _post_json(WEBHOOK, update, {"X-Telegram-Bot-Api-Secret-Token": SECRET})
    return status


def user_obj(uid: int) -> dict:
    return {"id": uid, "is_bot": False, "first_name": "Влад", "username": "esmien", "language_code": "ru"}


def send_text(text: str, uid: int = OWNER, chat: int = CHAT) -> int:
    return post(
        {
            "update_id": next_uid(),
            "message": {
                "message_id": next_mid(),
                "date": int(time.time()),
                "chat": {"id": chat, "type": "private", "first_name": "Влад", "username": "esmien"},
                "from": user_obj(uid),
                "text": text,
            },
        }
    )


def send_sticker(uid: int = OWNER, chat: int = CHAT) -> int:
    return post(
        {
            "update_id": next_uid(),
            "message": {
                "message_id": next_mid(),
                "date": int(time.time()),
                "chat": {"id": chat, "type": "private"},
                "from": user_obj(uid),
                "sticker": {
                    "file_id": "CAACAgIAAxkBAAIBtest",
                    "file_unique_id": "AgADtest",
                    "type": "regular",  # обязателен: без него aiogram валит Update
                    "width": 512,
                    "height": 512,
                    "is_animated": False,
                    "is_video": False,
                },
            },
        }
    )


def send_cb(data: str, mid: int | None = None, uid: int = OWNER, chat: int = CHAT, text: str = "") -> int:
    return post(
        {
            "update_id": next_uid(),
            "callback_query": {
                "id": uuid.uuid4().hex,
                "from": user_obj(uid),
                "chat_instance": "test-chat-instance",
                "data": data,
                "message": {
                    "message_id": mid or next_mid(),
                    "date": int(time.time()),
                    "chat": {"id": chat, "type": "private"},
                    "from": {"id": BOT_ID, "is_bot": True, "first_name": "Lyria"},
                    "text": text,
                },
            },
        }
    )


def tg(method: str, **params) -> dict:
    _, body = _post_json(f"https://api.telegram.org/bot{TOKEN}/{method}", params)
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return {"ok": False, "description": body[:200].decode("utf-8", "ignore")}


def _logs(container: str, since_epoch: float) -> str:
    """docker logs пишет в stderr — читаем оба потока."""
    out = subprocess.run(["docker", "logs", container, "--since", str(int(since_epoch) - 1)], capture_output=True, text=True)
    return out.stdout + out.stderr


def wait_marker(marker: str, since_epoch: float, timeout: float = 180.0) -> bool:
    """События обогащения логирует ENRICHER-WORKER, а не бот — смотрим оба."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(marker in _logs(c, since_epoch) for c in ("lyria-bot", "lyria-enricher-worker")):
            return True
        time.sleep(3)
    return False


def log_errors(since_epoch: float) -> list[str]:
    """Ошибки без шума от форж-callback («query is too old»)."""
    text = _logs("lyria-bot", since_epoch) + _logs("lyria-generation-worker", since_epoch)
    noise = ("query is too old", "query ID is invalid", "Необработанная ошибка")
    return [ln[:180] for ln in text.splitlines() if ("Traceback" in ln or "ERROR" in ln) and not any(n in ln for n in noise)]


def last_gid() -> int:
    return int(sql("select coalesce(max(id),0) from generations"))


def wait_gen_status(gid: int, statuses: tuple[str, ...], timeout: float = 300.0) -> str:
    deadline = time.time() + timeout
    last = "?"
    while time.time() < deadline:
        last = sql(f"select status from generations where id={gid}") or "?"
        if last in statuses:
            return last
        time.sleep(3)
    return last


def current_max() -> int:
    """Точный последний message_id чата: шлём пробное сообщение и удаляем его."""
    res = tg("sendMessage", chat_id=CHAT, text="(техпроверка стенда)")
    mid = (res.get("result") or {}).get("message_id")
    if mid:
        tg("deleteMessage", chat_id=CHAT, message_id=mid)
        return mid
    return 0


def find_keyboards(from_id: int, to_id: int) -> list[tuple[int, str]]:
    """Все сообщения бота с инлайн-клавиатурой в окне (клавиатуры при этом снимаются)."""
    out: list[tuple[int, str]] = []
    for mid in range(max(1, from_id), to_id + 1):
        res = tg("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": []})
        if res.get("ok"):
            msg = res["result"]
            out.append((mid, msg.get("text") or msg.get("caption") or ""))
        time.sleep(0.08)
    return out


SEED_TITLE = r'''
import asyncio, json, os
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from core.config import settings
from domains.enricher.handlers import _build_generation_prompt
from domains.enricher.service import save_enriched_prompt
from domains.generation.fsm import GenerationStates

async def main():
    chat = int(os.environ["SEED_CHAT"]); mode = os.environ.get("SEED_MODE", "approve")
    st = RedisStorage.from_url(settings.redis.redis_url)
    key = StorageKey(bot_id=int(os.environ["SEED_BOT"]), chat_id=chat, user_id=chat)
    data = await st.get_data(key)
    idea = data.get("prompt") or ""
    enriched = data.get("enriched_prompt") if mode == "approve" else None
    if mode == "approve" and not enriched:
        print(json.dumps({"ok": False, "error": "no enriched_prompt in FSM"})); return
    final = _build_generation_prompt(enriched or idea)
    await save_enriched_prompt(tg_id=chat, initial_prompt=idea, enriched_prompt=enriched or idea)
    data.update({"prompt": final, "generating": False, "gen_id": None, "enriching": False, "title": None})
    await st.set_data(key, data)
    await st.set_state(key, GenerationStates.waiting_for_title)
    print(json.dumps({"ok": True, "mode": mode, "final_len": len(final), "idea_len": len(idea)}))
    await st.close()

asyncio.run(main())
'''

SEED_FEEDBACK = r'''
import asyncio, json
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from core.config import settings
from domains.feedback.fsm import FeedbackStates

async def main():
    st = RedisStorage.from_url(settings.redis.redis_url)
    key = StorageKey(bot_id=8942340701, chat_id=214062001, user_id=214062001)
    await st.set_state(key, FeedbackStates.waiting_feedback)
    data = await st.get_data(key)
    data.update({"gen_id": int(__import__("os").environ["SEED_GEN"]), "feedback_text": None, "feedback_prompt_message_id": None})
    await st.set_data(key, data)
    print(json.dumps({"ok": True, "state": await st.get_state(key)}))
    await st.close()

asyncio.run(main())
'''


def _exec_in_bot(script: str, env: dict[str, str]) -> dict:
    args = ["docker", "exec", "-i"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    args += ["lyria-bot", "python", "-"]
    out = subprocess.run(args, input=script, capture_output=True, text=True)
    tail = (out.stdout + out.stderr).strip().splitlines()
    try:
        return json.loads(tail[-1])
    except Exception:
        return {"ok": False, "raw": (tail[-1][:300] if tail else "")}


def seed_title(mode: str = "approve") -> dict:
    return _exec_in_bot(SEED_TITLE, {"SEED_CHAT": str(CHAT), "SEED_BOT": str(BOT_ID), "SEED_MODE": mode})


def seed_feedback(gen_id: int) -> dict:
    return _exec_in_bot(SEED_FEEDBACK, {"SEED_GEN": str(gen_id)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-generate", action="store_true", help="только бесплатные сценарии (без запросов к OpenRouter)")
    args = ap.parse_args()

    started = time.time()
    results: list[dict] = []
    ART.mkdir(parents=True, exist_ok=True)

    def check(name: str, ok: bool, detail: object = "") -> None:
        results.append({"name": name, "ok": bool(ok)})
        log("CHECK", {"name": name, "ok": bool(ok), "detail": detail})

    base_gid = last_gid()
    log("START", {"base_gid": base_gid, "generate": not args.no_generate})
    send_text("/cancel")
    time.sleep(2)

    # S1: доступ
    sql(f"update users set is_authorized=false where tg_id={OTHER}")
    send_text("/start", uid=OTHER)
    time.sleep(2)
    check("S1 /start без доступа не авторизует", sql(f"select is_authorized from users where tg_id={OTHER}") == "f")
    for _ in range(4):
        send_text("not-a-key", uid=OTHER)
        time.sleep(1.0)
    send_text("not-a-key", uid=OTHER)
    time.sleep(1.5)
    check("S1 5 неверных ключей — доступа нет", sql(f"select is_authorized from users where tg_id={OTHER}") == "f")
    send_text("/start", uid=OTHER)
    time.sleep(1)
    send_text(ACCESS_KEY, uid=OTHER)
    time.sleep(2)
    check("S1 верный ключ авторизует", sql(f"select is_authorized from users where tg_id={OTHER}") == "t")

    # S2/S3: меню и старт сценария
    send_text("/start")
    time.sleep(1.5)
    send_text("🎵 Сгенерировать")
    time.sleep(2)

    # S4: валидация ввода
    send_text("   ")
    time.sleep(1)
    send_text("Жанр: \n\nНастроение: \n\nИнструменты: \n\nТемп и ритм: \n\nГолос: \n\nТекст песни: \n")
    time.sleep(1)
    send_text("а" * 4001)
    time.sleep(1)
    send_sticker()
    time.sleep(1.5)
    errs = log_errors(started)
    check("S4 пустой/шаблон/4001 симв./стикер без падений", not errs, errs[-3:])

    if args.no_generate:
        log("SUMMARY", {"mode": "no-generate", "failed": [r["name"] for r in results if not r["ok"]]})
        return 0

    # S5: happy path
    t = time.time()
    send_text(
        "Песня про DevOps-инженера, который в три часа ночи будит прод, варит кофе "
        "и разговаривает с логами как со старым другом. Жанр: русский рок с гитарой. "
        "Мужской вокал, немного иронии."
    )
    check("S5 обогащение -> предпросмотр", wait_marker("Enrichment result delivered", t, 180))
    mx = current_max()
    kbs = find_keyboards(mx - 8, mx)
    if kbs:
        log("S5_PREVIEW", kbs[-1][1][:1200])
    seed = seed_title("approve")
    log("S5_SEED", seed)
    check("S5 переход к вводу названия", bool(seed.get("ok")))
    send_text("а" * 101)
    time.sleep(1.5)
    send_text("Ночной дежурный")
    time.sleep(4)
    gid = last_gid()
    st = wait_gen_status(gid, ("success", "failed", "cancelled"))
    check("S5 генерация success", st == "success", {"gid": gid, "status": st})
    log("S5_ROW", sql(f"select status,delivery_status,audio_size,title from generations where id={gid}"))

    # оценка + текстовый отзыв (кнопка «Отправить отзыв» требует реального message_id,
    # поэтому состояние waiting_feedback ставим production-хранилищем)
    send_cb(f"fb:like:{gid}")
    time.sleep(2)
    log("S5_FEEDBACK_SEED", seed_feedback(gid))
    send_text("Трек зашёл, но в припеве хотелось бы больше гитары и меньше страданий.")
    time.sleep(3)
    fb = sql(f"select is_liked, coalesce(feedback,'') from generation_feedbacks where generation_id={gid} order by id desc limit 1")
    check("S5 оценка и текстовый отзыв сохранены", "|" in fb and len(fb.split("|")[1]) > 5, fb)

    # S6: ветка «Изменить»
    t = time.time()
    send_text("🎵 Сгенерировать")
    time.sleep(1.5)
    send_text("Песня про кота, который лежит на клавиатуре и ломает деплой. Жанр: весёлый панк.")
    wait_marker("Enrichment result delivered", t, 180)
    mx = current_max()
    kbs = find_keyboards(mx - 8, mx)
    send_cb("prompt:edit", mid=kbs[-1][0] if kbs else None)  # state меняется до answer()
    time.sleep(2)
    send_text("Добавь припев про то, что кот нажал Ctrl+Z на всей жизни. Сделай в стиле дворового шансона с баяном.")
    ok = wait_marker("Enrichment result delivered", time.time(), 180)
    check("S6 «Изменить» -> повторное обогащение", ok)
    seed = seed_title("approve")
    send_text("Кот на клавиатуре")
    time.sleep(4)
    gid = last_gid()
    st = wait_gen_status(gid, ("success", "failed", "cancelled"))
    check("S6 генерация после правок success", st == "success", {"gid": gid, "status": st})
    send_cb(f"fb:dislike:{gid}")
    time.sleep(2)
    send_cb(f"fb:finish:{gid}")
    time.sleep(2)
    check("S6 дизлайк сохранён", sql(f"select count(*) from generation_feedbacks where generation_id={gid}") != "0")

    # S7: фоллбэк — промпт без обогащения
    t = time.time()
    send_text("🎵 Сгенерировать")
    time.sleep(1.5)
    send_text("Частушки про сисадмина, который потерял пакет и нашёл себя. Баян, озорное настроение.")
    wait_marker("Enrichment result delivered", t, 180)
    seed = seed_title("fallback")
    check("S7 промпт без обогащения собран", bool(seed.get("ok")), seed.get("final_len"))
    send_text("Пакет не найден")
    time.sleep(4)
    gid = last_gid()
    st = wait_gen_status(gid, ("success", "failed", "cancelled"))
    check("S7 генерация без обогащения success", st == "success", {"gid": gid, "status": st})

    # S8: отмена (деньги уже списаны, если запрос успел уйти — это ожидаемо)
    t = time.time()
    send_text("🎵 Сгенерировать")
    time.sleep(1.5)
    send_text("Баллада про сгоревший сервер и человека, который его любил. Грустно, фортепиано.")
    wait_marker("Enrichment result delivered", t, 180)
    seed_title("approve")
    send_text("Сервер не выдержал")
    time.sleep(3)
    gid = last_gid()
    send_text("🎵 Сгенерировать")
    time.sleep(1)
    send_text("❌ Отмена")
    st = wait_gen_status(gid, ("cancelled", "success", "failed"), 90)
    check("S8 отмена -> cancelled без доставки", st == "cancelled", {"gid": gid, "status": st})
    log("S8_ROW", sql(f"select status,delivery_status,coalesce(audio_size,0) from generations where id={gid}"))

    # S9: команда в состоянии ввода идеи (известный баг: уходит в обогащение)
    t = time.time()
    send_text("🎵 Сгенерировать")
    time.sleep(2)
    send_text("/credits")
    time.sleep(2)
    bug = "Enrichment command published" in _logs("lyria-bot", t)
    check("S9 НАЙДЕНО: команда в режиме ввода идеи уходит в обогащение", not bug)
    time.sleep(12)
    send_text("/cancel")

    # S10: кредиты
    t = time.time()
    send_text("💳 Кредиты")
    time.sleep(5)
    errs = log_errors(t)
    check("S10 кредиты без ошибок", not errs, errs[-2:])

    # S11: выход/вход
    send_text("🚪 Выйти", uid=OTHER)
    time.sleep(2)
    check("S11 выход снял доступ", sql(f"select is_authorized from users where tg_id={OTHER}") == "f")
    send_text("🎵 Сгенерировать", uid=OTHER)
    time.sleep(2)
    send_text("/start", uid=OTHER)
    time.sleep(1)
    send_text(ACCESS_KEY, uid=OTHER)
    time.sleep(2)
    check("S11 повторный вход по ключу", sql(f"select is_authorized from users where tg_id={OTHER}") == "t")

    # финал: артефакты
    rows = sql(f"select id,status,delivery_status,coalesce(audio_size,0),title,audio_path from generations where id>{base_gid} order by id")
    log("FINAL_ROWS", rows)
    for line in rows.splitlines():
        parts = line.split("|")
        if len(parts) >= 6 and parts[5]:
            r = subprocess.run(["docker", "cp", f"lyria-generation-worker:{parts[5]}", str(ART / f"gen_{parts[0]}.mp3")], capture_output=True, text=True)
            if r.returncode != 0:
                log("COPY_FAIL", {"gid": parts[0], "err": r.stderr.strip()[:120]})
    check("Итог: нет падений за прогон", not log_errors(started), log_errors(started)[-5:])
    log("SUMMARY", {"failed": [r["name"] for r in results if not r["ok"]], "elapsed_s": round(time.time() - started)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
