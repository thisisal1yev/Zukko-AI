"""Load settings from environment (never commit real secrets)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _req(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


TELEGRAM_TOKEN = _req("TELEGRAM_TOKEN")
OPENROUTER_VISION_KEY = _req("OPENROUTER_VISION_KEY")
OPENROUTER_TEXT_KEY = _req("OPENROUTER_TEXT_KEY")

VISION_MODEL = os.environ.get("VISION_MODEL", "google/gemini-2.0-flash-001").strip()
TEXT_MODEL = os.environ.get("TEXT_MODEL", "google/gemini-2.0-flash-001").strip()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEMO_LESSON_URL = os.environ.get("DEMO_LESSON_URL", "").strip()
TEACHER_CHANNEL_URL = os.environ.get("TEACHER_CHANNEL_URL", "").strip()

# Offer demo / channel after this many "low" writing scores (approximate band threshold)
LOW_BAND_THRESHOLD = 5.5
LOW_BAND_STREAK_FOR_DEMO = 2
