#!/usr/bin/env python3
"""Probe the media routes of the LiteLLM gateway from inside the litellm container.

Run:
    docker exec -i litellm /app/.venv/bin/python - < scripts/probe-media-endpoints.py
    docker exec -i litellm /app/.venv/bin/python - --images < scripts/probe-media-endpoints.py

Why inside the container: it has no curl/wget, and the master key is already in
its env as LITELLM_MASTER_KEY — this script reads it there and never prints it.

Default checks are cheap (voices + two short TTS calls). --images also POSTs one
image generation, which costs real money, so it is opt-in.

Overridable via env: PROBE_TTS_MODEL, PROBE_TTS_VOICE, PROBE_IMG_MODEL.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4000"
KEY = os.environ.get("LITELLM_MASTER_KEY", "")
TTS_MODEL = os.environ.get("PROBE_TTS_MODEL", "tts.openrouter/gemini-3.8-flash-lite-tts")
TTS_VOICE = os.environ.get("PROBE_TTS_VOICE", "zephyr")
IMG_MODEL = os.environ.get("PROBE_IMG_MODEL", "img.openrouter/hy-image-v3.5")


def call(path, body=None, timeout=120):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.headers.get("content-type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, None, e.read()
    except Exception as e:  # network error / timeout
        return None, None, f"{type(e).__name__}: {e}".encode()


def show(label, status, ctype, payload):
    if ctype is None:
        detail = payload[:200].decode("utf-8", "replace")
    else:
        detail = f"{len(payload)} bytes magic={payload[:12]!r}"
    print(f"{label}: status={status} ctype={ctype} {detail}")


if not KEY:
    sys.exit("LITELLM_MASTER_KEY is not set in this environment")

show("voices", *call("/v1/audio/voices", None, 30))
show("tts default", *call("/v1/audio/speech", {"model": TTS_MODEL, "input": "probe", "voice": TTS_VOICE}))
show(
    "tts mp3",
    *call(
        "/v1/audio/speech",
        {"model": TTS_MODEL, "input": "probe", "voice": TTS_VOICE, "response_format": "mp3"},
    ),
)

if "--images" in sys.argv:
    show(
        "image",
        *call(
            "/v1/images/generations",
            {"model": IMG_MODEL, "prompt": "a red cube on a white table", "size": "1024x1024"},
            180,
        ),
    )
