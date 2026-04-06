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

# Majburiy kanallar (foydalanuvchi azo bo'lishi shart)
PROJECT_CHANNEL_URL = os.environ.get("PROJECT_CHANNEL_URL", "").strip()
SPONSOR_CHANNEL_URL = os.environ.get("SPONSOR_CHANNEL_URL", "").strip()
PROJECT_CHANNEL = os.environ.get("PROJECT_CHANNEL", "").strip().lstrip("@")
SPONSOR_CHANNEL = os.environ.get("SPONSOR_CHANNEL", "").strip().lstrip("@")

# Offer demo / channel after this many "low" writing scores (approximate band threshold)
LOW_BAND_THRESHOLD = 5.5
LOW_BAND_STREAK_FOR_DEMO = 2

# =============================================================================
# NARXLAR VA LIMITLAR (Prompt.md asosida)
# =============================================================================

# Writing tahlili narxlari
WRITING_ANALYSIS_COST = float(os.environ.get("WRITING_ANALYSIS_COST", "2"))
WRITING_EXTRA_COST = float(os.environ.get("WRITING_EXTRA_COST", "0.5"))  # 4-chi va undan keyingi
WRITING_DAILY_FREE = int(os.environ.get("WRITING_DAILY_FREE", "3"))  # kunlik 3 marta

# Vocabulary narxi
VOCAB_COST = float(os.environ.get("VOCAB_COST", "0.5"))

# Paraphrase o'yini narxi
PARAPHRASE_COST = float(os.environ.get("PARAPHRASE_COST", "3"))
PARAPHRASE_DAILY_FREE = int(os.environ.get("PARAPHRASE_DAILY_FREE", "3"))  # kunlik 3 marta

# Combo tizimi
COMBO_THRESHOLD_1 = 3  # 3 combo -> 1 free spin
COMBO_THRESHOLD_2 = 5  # 5 combo -> 2 free spins

# O'qituvchi tariflari
TEACHER_PRO_WEEKLY = int(os.environ.get("TEACHER_PRO_WEEKLY", "100"))
TEACHER_PREMIUM_MONTHLY = int(os.environ.get("TEACHER_PREMIUM_MONTHLY", "160"))

# Boshlang'ich tanga bonusi
INITIAL_COINS_BONUS = float(os.environ.get("INITIAL_COINS_BONUS", "5"))

# =============================================================================
# BARABAN (WHEEL) TIZIMI
# =============================================================================

# --- Oddiy Baraban (4 tanga) ---
WHEEL_BASIC_COST = int(os.environ.get("WHEEL_BASIC_COST", "4"))
WHEEL_BASIC_VOCAB = float(os.environ.get("WHEEL_BASIC_VOCAB", "25"))  # 25%
WHEEL_BASIC_WRITING = float(os.environ.get("WHEEL_BASIC_WRITING", "20"))  # 20%
WHEEL_BASIC_PARAPHRASE_DAY = float(os.environ.get("WHEEL_BASIC_PARAPHRASE_DAY", "15"))  # 15%
WHEEL_BASIC_10_COINS = float(os.environ.get("WHEEL_BASIC_10_COINS", "25"))  # 25%
WHEEL_BASIC_TUTOR_DAY = float(os.environ.get("WHEEL_BASIC_TUTOR_DAY", "10"))  # 10%
WHEEL_BASIC_RESPIN = float(os.environ.get("WHEEL_BASIC_RESPIN", "5"))  # 5%

# --- Premium Baraban (40 tanga) ---
WHEEL_PREMIUM_COST = int(os.environ.get("WHEEL_PREMIUM_COST", "40"))
WHEEL_PREMIUM_40_COINS = float(os.environ.get("WHEEL_PREMIUM_40_COINS", "20"))  # 20%
WHEEL_PREMIUM_WRITING_PRO = float(os.environ.get("WHEEL_PREMIUM_WRITING_PRO", "15"))  # 15%
WHEEL_PREMIUM_VOCAB_KING = float(os.environ.get("WHEEL_PREMIUM_VOCAB_KING", "15"))  # 15%
WHEEL_PREMIUM_JACKPOT = float(os.environ.get("WHEEL_PREMIUM_JACKPOT", "5"))  # 5%
WHEEL_PREMIUM_LUCKY_DAYS = float(os.environ.get("WHEEL_PREMIUM_LUCKY_DAYS", "25"))  # 25%
WHEEL_PREMIUM_MEGA_RESPIN = float(os.environ.get("WHEEL_PREMIUM_MEGA_RESPIN", "20"))  # 20%
