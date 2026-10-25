# Media pipeline (images / TTS through LiteLLM)

> Loaded from the `ai-stack` skill. Read this when image generation, TTS, `cptr`, model routing for media.

## Media pipeline (images / TTS through LiteLLM)

Images and speech are **not** separate services — both go through the same gateway: Open WebUI → `http://litellm:4000/v1` → an `img.openrouter/*` or `tts.openrouter/*` model group. Read the wiring from `webui_db.config` (never from container env):

```bash
sudo -u postgres psql -d webui_db -Atc "select key||' = '||left(value::text,200) from config where key ~* 'audio|tts|image|stt' and key not like '%api_key%' order by key;"
```

Current shape: `image_generation.engine=openai` + `image_generation.model=img.openrouter/hy-image-v3.5`; `audio.tts.engine=openai` + `audio.tts.model=tts.openrouter/gemini-3.8-flash-lite-tts` + `audio.tts.voice=zephyr`.

- **Gemini TTS supports `response_format=pcm` ONLY.** `mp3` → `400 litellm.BadRequestError: [OI]Exception - Gemini TTS only supports response_format="pcm"`; `wav` → `400 invalid_value ... expected one of "mp3"|"pcm"`. The default (no `response_format`) answers `200` with `content-type: audio/pcm` and **headerless raw PCM** (magic bytes are zeros, ~48 KB/s at 24 kHz 16-bit mono). Do not "fix" TTS by forcing `mp3` — that is the exact request that fails.
- **It plays only because Open WebUI transcodes.** `transcode_audio_to_mp3` in `routers/audio/__init__.py` special-cases `audio/pcm|audio/l16|audio/raw` (24 kHz/16-bit/mono defaults, pydub + ffmpeg, both present in the image) and writes mp3; it returns early and writes the raw bytes when `BYPASS_PYDUB_PREPROCESSING` is set. So the TTS chain depends on that flag staying unset and on ffmpeg/pydub surviving the OWUI upgrade.
- **`voice` is provider-specific.** `zephyr` is a Gemini voice; after pointing `audio.tts.model` at a non-Gemini group the request 400s on the voice. Re-pick the voice whenever the TTS model changes.
- **Probe TTS without ever printing the key** — run inside the gateway, judge content-type and body bytes, not the status code alone:
  ```bash
  docker exec litellm /app/.venv/bin/python -c "import os,json,urllib.request; k=os.environ['LITELLM_MASTER_KEY']; b=json.dumps({'model':'tts.openrouter/gemini-3.8-flash-lite-tts','input':'тест','voice':'zephyr'}).encode(); r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:4000/v1/audio/speech',data=b,headers={'Authorization':'Bearer '+k,'Content-Type':'application/json'})); d=r.read(); print(r.status, r.headers.get('content-type'), len(d), d[:12])"
  ```
- **Probe the whole media surface with `scripts/probe-media-endpoints.py`** — `docker exec -i litellm /app/.venv/bin/python - < scripts/probe-media-endpoints.py` (append `--images` to also spend on one image generation). It prints status / content-type / magic bytes for voices, default TTS, `response_format=mp3` and optionally an image, and takes the key from the container env so nothing is printed.
- **Distinguish real use from your own probes** via the spend log: a `metadata::json->>'user_api_key'` of `litellm_proxy_master_key` means the row is yours; OWUI arrives under its own key alias. Zero `/api/audio/speech` lines in `docker logs open-webui` plus only master-key spend rows = the feature is unused, not "working".
- **Image failures are upstream-model flakiness, not gateway glue.** Group failures per model before blaming LiteLLM: `hy-image-v3.5` served every request, `gpt-image-2.5-sunburst` ~2/3, `muse-image` ~1/5. Report the split, and propose a fallback group rather than touching the proxy.
- **Treat `image_generation.enable` and observed traffic as separate facts.** The config flag can read `false` while `/v1/images/generations` answers `200`; find which switch actually governs before "fixing" the flag, and say so.
- **`edge-tts` (openai-edge-tts) is not a working fallback and is not part of lyria.** It is referenced by nothing (no OWUI config, no bot env), its upstream `wss://speech.platform.bing.com` has answered `403 Invalid response status`, and its API key is the image default `your_api_key_here`. Before counting any container as redundancy, exercise it with a real `/v1/audio/speech` call.

