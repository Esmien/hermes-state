"""codex-persona — system prompt section bound to the Codex-subscription group.

Why this exists: Hermes has one global ``agent.system_prompt`` (``/personality``
is a global overlay too), so a prompt cannot be bound to a model *group* in
config. Open WebUI presets bind a prompt per model, but only on the WebUI route;
a direct provider connection (alias ``sol``/``terra``/``luna`` -> openai-codex)
never passes through it.

This plugin registers a bounded system-prompt section whose renderer returns the
persona text only when the session runs on the Codex subscription route, and an
empty string otherwise (empty sections are dropped, so every other route is
byte-identical to a plugin-less Hermes).

Matching is by PROVIDER, not by model name: the whole subscription is covered
(``gpt-6.1-sol``, ``gpt-6.1-terra``, ``gpt-6-luna`` and whatever gets added
later). Model-id substrings can be added via ``CODEX_PERSONA_MODELS``
(comma-separated) for extra routes such as an OWUI-backed group.

Notes:
* The section is frozen for the life of a session — switch the model with
  ``/model sol`` and start a new session (``/new``) for the persona to apply.
* Prompt text lives in ``persona.md`` (Hermes caps a section at 4000 chars).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SECTION_ID = "codex-persona.prompt"
_DEFAULT_PROVIDERS = ("openai-codex", "codex")
_MAX_SECTION_CHARS = 3900
_PERSONA_FILE = Path(__file__).with_name("persona.md")


def _providers() -> tuple[str, ...]:
    """Provider ids (lowercase substrings) whose sessions receive the persona."""
    raw = os.environ.get("CODEX_PERSONA_PROVIDERS", "").strip()
    if raw:
        providers = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
        if providers:
            return providers
    return _DEFAULT_PROVIDERS


def _model_substrings() -> tuple[str, ...]:
    """Optional extra model-id substrings (e.g. an OWUI group name)."""
    raw = os.environ.get("CODEX_PERSONA_MODELS", "").strip()
    return tuple(m.strip().lower() for m in raw.split(",") if m.strip())


def _read_persona() -> str:
    try:
        return _PERSONA_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("codex-persona: cannot read %s: %s", _PERSONA_FILE, exc)
        return ""


def _matches(session_info) -> bool:
    provider = str(session_info.get("provider") or "").strip().lower()
    if provider and any(p in provider for p in _providers()):
        return True
    model = str(session_info.get("model") or "").strip().lower()
    extra = _model_substrings()
    return bool(model and extra and any(m in model for m in extra))


def _render(session_info) -> str:
    if not _matches(session_info):
        return ""
    return _read_persona()


def register(ctx) -> None:
    if not _read_persona():
        logger.warning("codex-persona: persona.md is empty or missing — no section registered")
        return
    ctx.register_system_prompt_section(_SECTION_ID, _render, max_chars=_MAX_SECTION_CHARS)
