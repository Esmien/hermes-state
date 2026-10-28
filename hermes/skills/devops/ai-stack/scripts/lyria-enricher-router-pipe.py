"""
title: Enricher (router)
author: Vlad
version: 2.5.1
required_open_webui_version: 0.6.0
description: Маршрутизатор стихи/идея на pplx-decider, две роли (poet/producer) с общей JSON-частью. Отдаёт боту готовый JSON контракта.
"""

import json
import re

import httpx
from pydantic import BaseModel, Field

SHARED = """ФОРМАТ ОТВЕТА: только один JSON-объект, без markdown и без текста вокруг.

СХЕМА:
{
  "genre_and_style": "string",
  "mood": "string",
  "instrumentation": ["string"],
  "tempo_bpm": 0,
  "vocal_style": "string",
  "language": "string",
  "lyrics": "string",
  "song_structure": ["string"]
}

ПОЛЯ-ПРОДЮСЕР (английский, словарь Lyria):
- genre_and_style: 1–3 термина + эпоха/регион. Словарь: Acid House, Breakbeat, Chillout, Chiptune, Deep House, Drum & Bass, Dubstep, EDM, Electro Swing, Glitch Hop, Hyperpop, Minimal Techno, Psytrance, Synthpop, Techno, Trance, Trip Hop, Vaporwave, 808 Hip Hop, Boom-Bap, Contemporary R&B, G-funk, Grime, Lo-Fi Hip Hop, Neo-Soul, Trap Beat, Alternative Country, Blues Rock, Classic Rock, Garage Rock, Indie Folk, Indie Pop, Post-Punk, 60s Psychedelic Rock, Shoegaze, Surf Rock, Acid Jazz, Afrobeat, Bossa Nova, Disco Funk, Funk, Jazz Fusion, Latin Jazz, Bluegrass, Celtic Folk, Cumbia, Polka, Reggae, Reggaeton, Salsa, Baroque, Orchestral Score, Piano Ballad, russian chanson, russian bard song, hardbass. Запрещены: cinematic, atmospheric, epic, emotional, vibe, fusion of styles, modern sound.
- mood: 2–3 слова из Ambient, Bright, Chill, Dark, Dreamy, Emotional, Ethereal, Euphoric, Funky, Groovy, Melancholic, Nostalgic, Ominous, Psychedelic, Relaxed, Soulful, Triumphant, Upbeat, Whimsical.
- instrumentation: 3–5 конкретных инструментов с характером звучания. Барабаны: Drumline — ТОЛЬКО марш/парад/оркестр; Funk Drums — ТОЛЬКО фанк/соул/диско. Для рока, панка, инди и метала не подставляй их в instrumentation: рисунок барабанов описывай в song_structure («driving rock drums, kick-snare-hat», «half-time tom groove», «fast punk beat»), а в instrumentation оставь гитары, бас и клавиши. Словарь: Buchla Synths, Clavichord, Dirty Synths, Harpsichord, Mellotron, Moog Oscillations, Ragtime Piano, Rhodes Piano, Smooth Pianos, Spacey Synths, Synth Pads, 303 Acid Bass, 808 Hip Hop Beat, Boomy Bass, Conga Drums, Drumline, Funk Drums, Precision Bass, Tabla, TR-909 Drum Machine, Funk Metal, Moombahton, New Jack Swing, Bhangra, Indian Classical, Irish Folk, Merengue, Renaissance Music, Bengal Baul, Banjo, Balalaika, Bouzouki, Cello, Charango, Dulcimer, Fiddle, Flamenco Guitar, Guitar, Harp, Koto, Lyre, Mandolin, Pipa, Shamisen, Shredding Guitar, Sitar, Slide Guitar, Viola Ensemble, Warm Acoustic Guitar, Alto Saxophone, Bagpipes, Bass Clarinet, Didgeridoo, Harmonica, Ocarina, Trumpet, Tuba, Woodwinds, Bongos, Djembe, Glockenspiel, Hang Drum, Kalimba, Maracas, Marimba, Mbira, Steel Drum, Vibraphone, bayan accordion, balalaika, domra. Запрещено писать просто synths/strings/drums/beats/various instruments.
- tempo_bpm: подбирай под текст и настроение, а не по умолчанию. Меланхолическая лирика и баллады 70–90; средний рок 95–110; энергичный рок и панк-рок 135–155; панк/хардкор/хардбасс 155–180; поп и соул 90–115. Просят «энергично/не растянуто» — не ниже 135; «медленно/проникновенно» — не выше 90. Если текст длинный и плотный (4+ куплета) — не выше 105, иначе певец захлёбывается.
- ДЫХАНИЕ: текст не должен звучать сплошным потоком. В lyrics разделяй смысловые блоки пустой строкой, а в song_structure для каждого куплета прямо прописывай паузы и прореживание: «vocal line, then a one-bar instrumental rest after each couplet», «stop-time on the last word», «two-beat silence and a drum fill before the chorus», «guitars drop out for one bar between lines».
- vocal_style: профиль (Female Soprano, Female Alto, Male Tenor, Male Baritone, Weathered Rocker) + подача одной фразой. Инструментал — "instrumental, no vocals".
- language: язык вокала, по умолчанию "Russian".
- song_structure: массив английских инструкций по секциям, например "[Intro] Solo balalaika, tape hiss, no vocals." Теги секций должны совпадать с тегами в lyrics.

ОРФОГРАФИЯ LYRICS: по-русски, без буквы ё, без знаков ударения и комбинирующих символов, без английских слов и транслита внутри строк. Бэки в скобках: (эй), (держи)."""

POEM_RULES = """РЕЖИМ: ГОТОВЫЙ ТЕКСТ / ПРАВКИ ГОТОВОГО ТЕКСТА.

0. Если в истории есть прошлый вариант и пользователь просит правку — ПРАВКА ГЛАВНЕЕ ЗАПРЕТОВ: выполни именно её (см. п.6). Запреты ниже действуют только на строки, которых правка не касается.
1. Текст автора — базово неприкосновенен: не переписывай строки, не меняй слова, порядок строк и РЕГИСТР без явной просьбы. Если автор написал слово с заглавной буквой внутри (занОзою) — сохрани это как ударение, это не ошибка.
2. НЕ дублируй и НЕ досоздавай строки, если об этом прямо не попросили. Сколько строк у автора — столько остаётся в lyrics (меняются только теги секций).
3. Разметь куплеты по 4 строки: [Verse 1], [Verse 2], ... Если строк не кратно 4 — последний куплет короче, это нормально.
4. [Chorus] — ТОЛЬКО если (а) автор сам повторил строфу дословно или пометил «припев», либо (б) пользователь прямо просит припев/рефрен. Во всех остальных случаях тега [Chorus] быть не должно: строфы идут подряд [Verse 1..N]. Не выделяй рефрен «по своему вкусу», даже если строфа кажется самой сильной. В случае (б) вынеси самую сильную авторскую строфу в [Chorus] и повторяй её по форме; слова не меняй, в куплетах не дублируй.
5. Если автор попросил сменить стиль/жанр/настроение — меняй только поля-продюсера, текст не трогай.
6. ПРАВКА ТЕКСТА — ИСКЛЮЧЕНИЕ ИЗ П.1–2: если пользователь прямо просит заменить, переписать или дописать конкретную строку/куплет/припев — выполни ровно эту просьбу, держа метр (7–9 слогов) и рифму исходного текста. Остальные строки не трогай, порядок сохраняй. «Допиши куплет» = добавить новый куплет в конец, старые не переписывать.
7. Сохраняй авторские переносы строк и пустые строки между смысловыми блоками — они задают дыхание песни. Не склеивай строки в сплошной поток.
8. Если в тексте есть готовые пометки [Verse]/[Chorus]/[Bridge] — сохрани их как есть.
9. Intro и Outro в lyrics не пиши: они инструментальные и живут только в song_structure."""

IDEA_RULES = """РЕЖИМ: АВТОР ПРИСЛАЛ ТОЛЬКО ИДЕЮ.

1. Напиши текст с нуля: 2 куплета по 4 строки, припев 3–4 строки, короткий бридж.
2. Куплет: 7–9 слогов в строке, единый метр, рифма ABAB или AABB, точная.
3. Запрещены саморифмы, рифмы одинаковых глагольных форм (упал/пропал) и штампы: душа, сердце, слезы, навсегда, судьба, ангел, «в этом мире», «кофе как смола».
4. Каждая строка — конкретный предмет, действие, время или место. Избегай слов с плавающим ударением, которые певец прочитает неверно: заноза/занозою, творог, звонит, петля, жалюзи, договор, свекла. Если слово нужно по смыслу — бери форму с однозначным ударением.
5. Припев при повторе меняется 1–2 строками; дословный повтор запрещён.
6. Разметь секции тегами на отдельной строке: [Verse 1], [Chorus], [Verse 2], [Chorus], [Bridge]. Intro и Outro в lyrics не пиши.
7. Если в истории есть прошлый вариант и пришла правка — меняй только то, о чём попросили (жанр, отдельная строка, куплет, темп), остальной текст и порядок строк сохраняй."""


class Pipe:
    class Valves(BaseModel):
        DECIDER_URL: str = Field(default="https://openrouter.ai/api/alpha/decisions")
        DECIDER_KEY: str = Field(
            default="", description="Ключ OpenRouter для decider-модели"
        )
        DECIDER_MODEL: str = Field(default="perplexity/pplx-decider-v1.2")
        DECIDER_TIMEOUT: int = Field(
            default=5, description="Таймаут маршрутизации, секунды"
        )
        DECIDER_THRESHOLD: float = Field(
            default=0.7, description="Ниже порога — безопасный дефолт poem"
        )

        API_BASE_URL: str = Field(default="http://litellm:4000/v1")
        API_KEY: str = Field(
            default="", description="Общий ключ LiteLLM для обеих ролей"
        )

        MODEL_POET: str = Field(
            default="qwen/qwen3-235b-a22b-instruct-2507",
            description="Поэт: генерация текста с нуля (idea)",
        )
        MODEL_PRODUCER: str = Field(
            default="qwen/qwen3-235b-a22b-instruct-2507",
            description="Продюсер: аранжировка готовых стихов (poem)",
        )

        # Тонкие настройки генератора
        TEMP_POET: float = Field(
            default=0.82, description="Температура для сочинения стихов"
        )
        TEMP_PRODUCER: float = Field(
            default=0.25, description="Температура для строгого JSON продюсера"
        )
        POET_TOP_P: float = Field(
            default=0.90,
            description="Top-P для поэта (отсечение мусорного хвоста токенов)",
        )
        POET_PRESENCE_PENALTY: float = Field(
            default=0.20, description="Штраф за повтор слов/образов в стихах"
        )

        MAX_TOKENS: int = Field(default=1200)
        TIMEOUT: int = Field(default=110)

    def __init__(self):
        self.type = "pipe"
        self.id = "enricher"
        self.name = "Enricher (router)"
        self.valves = self.Valves()

    async def _route(self, text: str) -> str:
        payload = {
            "model": self.valves.DECIDER_MODEL,
            "state": [text],
            "questions": {
                "route": {
                    "type": "choice",
                    "instructions": (
                        "Пользователь прислал готовый текст песни (стихи) или только идею/тему, "
                        "по которой текст нужно написать с нуля?"
                    ),
                    "criteria": {
                        "poem": "Прислан готовый авторский текст: строки уже написаны, их надо сохранить",
                        "idea": "Прислана только тема, идея, жанр или пожелания: самого текста песни нет",
                    },
                }
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.valves.DECIDER_TIMEOUT) as client:
                response = await client.post(
                    self.valves.DECIDER_URL,
                    headers={
                        "Authorization": f"Bearer {self.valves.DECIDER_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            response.raise_for_status()
            answer = (response.json().get("answers") or {}).get("route") or {}
            choice = answer.get("choice")
            probabilities = answer.get("probabilities") or {}
            if choice not in ("poem", "idea"):
                return "poem"
            if float(probabilities.get(choice, 0)) < self.valves.DECIDER_THRESHOLD:
                return "poem"
            return choice
        except Exception:
            return "poem"

    async def _produce(
        self,
        messages: list[dict],
        rules: str,
        model: str,
        temperature: float,
        top_p: float = 1.0,
        presence_penalty: float = 0.0,
    ) -> str:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": f"{SHARED}\n\n{rules}"}]
            + messages,
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "max_tokens": self.valves.MAX_TOKENS,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT) as client:
            response = await client.post(
                f"{self.valves.API_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.valves.API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _sanitize(raw: str, task: str = "", route: str = "poem") -> str:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return text
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return text
        if not isinstance(data, dict):
            return text
        data.setdefault("genre_and_style", "russian rock")
        data.setdefault("mood", "Melancholic")
        data.setdefault("vocal_style", "Male Baritone")
        data.setdefault("language", "Russian")
        if not isinstance(data.get("instrumentation"), list):
            data["instrumentation"] = [
                str(data.get("instrumentation") or "warm acoustic guitar")
            ]
        if not isinstance(data.get("song_structure"), list):
            data["song_structure"] = []
        try:
            data["tempo_bpm"] = int(data.get("tempo_bpm") or 110)
        except (TypeError, ValueError):
            data["tempo_bpm"] = 110
        if not data.get("lyrics"):
            # модель вернула JSON без текста — не теряем структуру, подставляем исходник
            if route == "poem" and task.strip():
                data["lyrics"] = task.strip()
            else:
                data["lyrics"] = "[Verse 1]\nТекст не сгенерирован"
        return json.dumps(data, ensure_ascii=False)

    async def pipe(
        self, body: dict, __user__: dict = None, __event_emitter__=None
    ) -> str:
        messages = [
            m
            for m in body.get("messages", [])
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        task = messages[-1]["content"] if messages else ""
        is_edit = any(m["role"] == "assistant" for m in messages[:-1])
        route = "poem" if is_edit else await self._route(task)

        if route == "poem":
            raw = await self._produce(
                messages=messages,
                rules=POEM_RULES,
                model=self.valves.MODEL_PRODUCER,
                temperature=self.valves.TEMP_PRODUCER,
                top_p=1.0,
                presence_penalty=0.0,
            )
        else:
            raw = await self._produce(
                messages=messages,
                rules=IDEA_RULES,
                model=self.valves.MODEL_POET,
                temperature=self.valves.TEMP_POET,
                top_p=self.valves.POET_TOP_P,
                presence_penalty=self.valves.POET_PRESENCE_PENALTY,
            )

        return self._sanitize(raw, task=task, route=route)
