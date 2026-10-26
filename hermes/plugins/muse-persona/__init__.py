"""muse-persona — per-model system prompt section.

Why this exists: Hermes has one global ``agent.system_prompt`` (``/personality`` is
also a global overlay), so a prompt cannot be bound to a single model in config.
Open WebUI presets do bind a prompt per model, but only on the WebUI route; a
direct provider connection (alias -> api.opencode.ai) never passes through it.

This plugin registers a bounded system-prompt section whose renderer returns the
persona text only when the session's model matches the configured prefixes, and
an empty string otherwise (empty sections are dropped, so other models are
byte-identical to a plugin-less Hermes).

Notes:
* The section is frozen for the life of a session — switch the model with
  ``/model muse`` and start a new session (``/new``) for the persona to apply.
* Prompt text lives in ``persona.md`` (≤ 4000 chars, Hermes' section cap).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SECTION_ID = "muse-persona.prompt"
_DEFAULT_MODEL_PREFIXES = ("muse",)
_MAX_SECTION_CHARS = 4000
_PERSONA_FILE = Path(__file__).with_name("persona.md")


def _model_prefixes() -> tuple[str, ...]:
    """Model-id prefixes (lowercase) that receive the persona."""
    raw = os.environ.get("MUSE_PERSONA_MODELS", "").strip()
    if raw:
        prefixes = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
        if prefixes:
            return prefixes
    return _DEFAULT_MODEL_PREFIXES


def _read_persona() -> str:
    try:
        return _PERSONA_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("muse-persona: cannot read %s: %s", _PERSONA_FILE, exc)
        return ""


def _render(session_info) -> str:
    model = str(session_info.get("model") or "").strip().lower()
    # Substring match: the same model arrives as ``muse`` (alias), ``muse-spark-1.3-contributor``
    # (OpenCode) or ``meta/muse-spark-1.3-contributor`` (OpenRouter fallback).
    if not model or not any(p in model for p in _model_prefixes()):
        return ""
    return _read_persona()


def register(ctx) -> None:
    if not _read_persona():
        logger.warning("muse-persona: persona.md is empty — no section registered")
        return
    ctx.register_system_prompt_section(_SECTION_ID, _render, max_chars=_MAX_SECTION_CHARS)
