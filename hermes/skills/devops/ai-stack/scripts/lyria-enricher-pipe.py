"""
title: Lyria Enricher (2-stage)
author: Vlad
version: 1.0.0
required_open_webui_version: 0.6.0
description: Двухступенчатый обогатитель песен под Lyria 3 — songwriter + продюсер-редактор, на выходе строгий JSON контракта бота.
"""

import json
import re

import httpx
from pydantic import BaseModel, Field

DRAFT_SYSTEM = """Ты — русский поэт-песенник. Пишешь текст по заявке пользователя.

ТРЕБОВАНИЯ К ТЕКСТУ:
1. Куплет — ровно 4 строки по 7–10 слогов. Внутри куплета один метр, строки не должны спотыкаться при чтении вслух.
2. Рифма ABAB или AABB, точная, на последнем ударном слоге.
3. Запрещены: саморифма (слово с самим собой), рифмы из одинаковых глагольных форм (упал/пропал, теряю/роняю), клише — душа, сердце, слезы, навсегда, судьба, ангел, «как смола», «в этом мире», «мы вместе».
4. Каждая строка — конкретный предмет, действие, время или место. Никаких абстракций и пафоса.
5. Припев — 3–4 строки с коротким хуком. Повторяя припев, меняй 1–2 строки, дословный повтор не нужен.
6. Секции размечай тегами на отдельной строке: [Verse 1], [Chorus], [Verse 2], [Bridge]. Intro и Outro не пиши словами — это инструментальные куски.
7. Бэки и подпевки — в скобках: (эй), (держи).
8. Пиши по-русски, без буквы ё, без английских слов внутри строк.

ЕСЛИ ПРИШЛА ИСТОРИЯ (заявка → прошлый вариант → правка): правка может касаться жанра, настроения, инструментов, темпа — переписывай текст целиком под новый стиль, а не одну строку.

Выведи ТОЛЬКО текст с тегами, без пояснений и без JSON."""

CRITIC_SYSTEM = """Ты — саунд-продюсер и редактор текста. На вход приходят заявка пользователя и черновик текста. Верни СТРОГО один JSON-объект, без markdown, без текста до и после.

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

ПОЛЯ:
- genre_and_style: 1–3 термина из словаря Lyria + эпоха/регион. Английский. Словарь: Acid House, Breakbeat, Chillout, Chiptune, Deep House, Drum & Bass, Dubstep, EDM, Electro Swing, Glitch Hop, Hyperpop, Minimal Techno, Psytrance, Synthpop, Techno, Trance, Trip Hop, Vaporwave, 808 Hip Hop, Boom-Bap, Contemporary R&B, G-funk, Grime, Lo-Fi Hip Hop, Neo-Soul, Trap Beat, Alternative Country, Blues Rock, Classic Rock, Garage Rock, Indie Folk, Indie Pop, Post-Punk, 60s Psychedelic Rock, Shoegaze, Surf Rock, Acid Jazz, Afrobeat, Bossa Nova, Disco Funk, Funk, Jazz Fusion, Latin Jazz, Bluegrass, Celtic Folk, Cumbia, Polka, Reggae, Reggaeton, Salsa, Baroque, Orchestral Score, Piano Ballad, russian chanson, russian bard song, hardbass. Запрещены абстракции: cinematic, atmospheric, epic, emotional, vibe, fusion of styles, modern sound.
- mood: 2–3 слова из списка Ambient, Bright, Chill, Dark, Dreamy, Emotional, Ethereal, Euphoric, Funky, Groovy, Melancholic, Nostalgic, Ominous, Psychedelic, Relaxed, Soulful, Triumphant, Upbeat, Whimsical.
- instrumentation: 3–5 конкретных инструментов с характером звучания. Словарь: Buchla Synths, Clavichord, Dirty Synths, Harpsichord, Mellotron, Moog Oscillations, Ragtime Piano, Rhodes Piano, Smooth Pianos, Spacey Synths, Synth Pads, 303 Acid Bass, 808 Hip Hop Beat, Boomy Bass, Conga Drums, Drumline, Funk Drums, Precision Bass, Tabla, TR-909 Drum Machine, Banjo, Balalaika, Bouzouki, Cello, Charango, Dulcimer, Fiddle, Flamenco Guitar, Guitar, Harp, Koto, Lyre, Mandolin, Pipa, Shamisen, Shredding Guitar, Sitar, Slide Guitar, Viola Ensemble, Warm Acoustic Guitar, Alto Saxophone, Bagpipes, Bass Clarinet, Didgeridoo, Harmonica, Ocarina, Trumpet, Tuba, Woodwinds, Bongos, Djembe, Glockenspiel, Hang Drum, Kalimba, Maracas, Marimba, Mbira, Steel Drum, Vibraphone, bayan accordion, domra. Запрещено писать просто synths/strings/drums/beats/various instruments.
- tempo_bpm: целое число. Баллада 60–80, поп и соул 90–110, рок и танцевальное 118–135, панк/хардкор/хардбасс 140–180.
- vocal_style: профиль (Female Soprano, Female Alto, Male Tenor, Male Baritone, Weathered Rocker) + подача одной фразой. Инструментал — "instrumental, no vocals".
- language: язык вокала, по умолчанию "Russian".
- lyrics: финальный текст с тегами секций, без буквы ё, без английских слов. В lyrics только вокальные секции: [Verse …], [Chorus], [Bridge]. Интро и аутро — инструментальные, их текст в lyrics не включай.
- Припев при повторе обязан отличаться 1–2 строками: дословный повтор запрещён. Куплет 4 строки по 7–10 слогов, рифма точная. Обязательные правки: убери саморифмы, глагольные созвучия и клише, выровняй метр, выкинь строки-заполнители без образа. Если строку пришлось переписать — сохрани смысл.
- song_structure: массив английских инструкций по секциям, например "[Intro] Solo balalaika, tape hiss, no vocals." Секции должны совпадать с тегами в lyrics.

Применяй правки пользователя ко ВСЕМ полям, которых они касаются: смена жанра меняет genre_and_style, instrumentation, tempo_bpm, vocal_style и текст.

Ответ — только JSON."""


class Pipe:
    class Valves(BaseModel):
        BASE_URL: str = Field(default="http://litellm:4000/v1", description="OpenAI-совместимый endpoint LiteLLM")
        API_KEY: str = Field(default="", description="Ключ LiteLLM для этого пайпа")
        DRAFT_MODEL: str = Field(default="google/gemini-4-argon", description="Модель-поэт")
        CRITIC_MODEL: str = Field(default="google/gemini-4-argon", description="Модель-продюсер")
        DRAFT_TEMPERATURE: float = Field(default=0.85, description="Температура поэта")
        CRITIC_TEMPERATURE: float = Field(default=0.25, description="Температура продюсера")
        TIMEOUT: int = Field(default=110, description="Таймаут одного вызова, секунды")
        DRAFT_MAX_TOKENS: int = Field(default=900, description="Потолок вывода поэта")
        CRITIC_MAX_TOKENS: int = Field(default=1100, description="Потолок вывода продюсера")

    def __init__(self):
        self.type = "pipe"
        self.id = "lyria_enricher"
        self.name = "Lyria Enricher (2-stage)"
        self.valves = self.Valves()

    async def _call(self, messages: list[dict], model: str, temperature: float, max_tokens: int) -> str:
        headers = {"Authorization": f"Bearer {self.valves.API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT) as client:
            response = await client.post(f"{self.valves.BASE_URL}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _history(body: dict) -> tuple[list[dict], str]:
        messages = [m for m in body.get("messages", []) if m.get("role") in ("user", "assistant") and m.get("content")]
        task = messages[-1]["content"] if messages else ""
        return messages, task

    @staticmethod
    def _sanitize(raw: str) -> str:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return text
        candidate = text[start : end + 1]
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return text
        if not isinstance(data, dict):
            return text
        data.setdefault("genre_and_style", "russian rock")
        data.setdefault("mood", "Melancholic")
        data.setdefault("vocal_style", "Male Baritone")
        data.setdefault("language", "Russian")
        if not isinstance(data.get("instrumentation"), list):
            data["instrumentation"] = [str(data.get("instrumentation") or "warm acoustic guitar")]
        if not isinstance(data.get("song_structure"), list):
            data["song_structure"] = []
        try:
            data["tempo_bpm"] = int(data.get("tempo_bpm") or 110)
        except (TypeError, ValueError):
            data["tempo_bpm"] = 110
        if not data.get("lyrics"):
            return text
        return json.dumps(data, ensure_ascii=False)

    async def pipe(self, body: dict, __user__: dict = None, __event_emitter__=None) -> str:
        messages, _task = self._history(body)

        draft = await self._call(
            [{"role": "system", "content": DRAFT_SYSTEM}] + messages,
            self.valves.DRAFT_MODEL,
            self.valves.DRAFT_TEMPERATURE,
            self.valves.DRAFT_MAX_TOKENS,
        )

        critic_input = "ЗАЯВКА И ИСТОРИЯ ПРАВОК:\n"
        for message in messages:
            role = "Пользователь" if message["role"] == "user" else "Прошлый вариант"
            critic_input += f"{role}: {message['content']}\n"
        critic_input += f"\nЧЕРНОВИК ТЕКСТА:\n{draft}"

        final = await self._call(
            [{"role": "system", "content": CRITIC_SYSTEM}, {"role": "user", "content": critic_input}],
            self.valves.CRITIC_MODEL,
            self.valves.CRITIC_TEMPERATURE,
            self.valves.CRITIC_MAX_TOKENS,
        )
        return self._sanitize(final)
