"""OpenRouter chat completions (vision + text)."""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import requests

from zukko import config

logger = logging.getLogger(__name__)


def _extract_message(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("empty choices from API")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts) or ""
    if content is None:
        return ""
    return str(content)


def ask_vision(prompt: str, image_path: str, timeout: int = 120) -> str:
    with open(image_path, "rb") as image_file:
        b64 = base64.b64encode(image_file.read()).decode("utf-8")
    payload = {
        "model": config.VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    r = requests.post(
        config.OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_VISION_KEY}",
        },
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    return _extract_message(r.json())


def ask_text(prompt: str, timeout: int = 90) -> str:
    payload = {
        "model": config.TEXT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(
        config.OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_TEXT_KEY}",
        },
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    return _extract_message(r.json())


def ask_text_safe(prompt: str, timeout: int = 90) -> str:
    try:
        return ask_text(prompt, timeout=timeout)
    except Exception as e:
        logger.exception("ask_text failed: %s", e)
        return f"⚠️ AI xizmatiga ulanib bo'lmadi: {e}"


def ask_vision_safe(prompt: str, image_path: str, timeout: int = 120) -> str:
    try:
        return ask_vision(prompt, image_path, timeout=timeout)
    except Exception as e:
        logger.exception("ask_vision failed: %s", e)
        return f"⚠️ Rasm tahlili muvaffaqiyatsiz: {e}"
