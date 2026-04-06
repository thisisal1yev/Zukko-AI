"""Baraban (Wheel) tizimi — Oddiy va Premium baraban logikasi."""
from __future__ import annotations

import random
from typing import Optional

from zukko import config, db


# =============================================================================
# ODDIY BARABAN — 6 ta variant
# =============================================================================

BASIC_REWARDS = [
    {
        "type": "vocab_booster",
        "label": "📚 Vocab Booster",
        "desc": "1 marta bepul Vocabulary mashqi",
        "probability": config.WHEEL_BASIC_VOCAB,
    },
    {
        "type": "writing_one_shot",
        "label": "📝 Writing One-Shot",
        "desc": "1 marta bepul Writing tahlili",
        "probability": config.WHEEL_BASIC_WRITING,
    },
    {
        "type": "paraphrase_day",
        "label": "🔄 1 Kunlik Paraphrase",
        "desc": "24 soat davomida Paraphrase o'yini cheksiz",
        "probability": config.WHEEL_BASIC_PARAPHRASE_DAY,
    },
    {
        "type": "coins_10",
        "label": "💰 10 Tanga",
        "desc": "Balansga 10 tanga bonus",
        "probability": config.WHEEL_BASIC_10_COINS,
    },
    {
        "type": "tutor_day",
        "label": "⚡ 1 Kunlik Tutor",
        "desc": "1 kun davomida AI Tutor bilan cheksiz muloqot",
        "probability": config.WHEEL_BASIC_TUTOR_DAY,
    },
    {
        "type": "re_spin",
        "label": "🎲 RE-SPIN",
        "desc": "Yana bir bor aylantirish imkoniyati!",
        "probability": config.WHEEL_BASIC_RESPIN,
    },
]

# =============================================================================
# PREMIUM BARABAN — 6 ta variant
# =============================================================================

PREMIUM_REWARDS = [
    {
        "type": "coins_40",
        "label": "💰 40 Tanga (Cashback)",
        "desc": "Tikkan pulingiz balansga to'liq qaytadi",
        "probability": config.WHEEL_PREMIUM_40_COINS,
    },
    {
        "type": "writing_pro",
        "label": "📝 Writing Pro",
        "desc": "2 kun davomida barcha Writing tahlillari bepul",
        "probability": config.WHEEL_PREMIUM_WRITING_PRO,
    },
    {
        "type": "vocab_king",
        "label": "📚 Vocab King",
        "desc": "3 kun davomida Vocabulary Booster cheksiz",
        "probability": config.WHEEL_PREMIUM_VOCAB_KING,
    },
    {
        "type": "jackpot",
        "label": "💎 JEKPOT",
        "desc": "1 hafta davomida Paraphrase o'yini cheksiz!",
        "probability": config.WHEEL_PREMIUM_JACKPOT,
    },
    {
        "type": "lucky_days",
        "label": "🎰 Lucky Days",
        "desc": "3 kun davomida Oddiy Barabanni BEPUL aylantirish!",
        "probability": config.WHEEL_PREMIUM_LUCKY_DAYS,
    },
    {
        "type": "mega_re_spin",
        "label": "🔄 MEGA RE-SPIN",
        "desc": "Yana bir bor aylantirish + 5 TANGA!",
        "probability": config.WHEEL_PREMIUM_MEGA_RESPIN,
    },
]


def _weighted_choice(rewards: list[dict]) -> dict:
    """Ehtimollikka qarab random tanlash."""
    total = sum(r["probability"] for r in rewards)
    rand = random.uniform(0, total)
    cumulative = 0.0
    for reward in rewards:
        cumulative += reward["probability"]
        if rand <= cumulative:
            return reward
    # Fallback (agar floating point xato bo'lsa)
    return rewards[-1]


def spin_basic_wheel(user_id: int) -> dict:
    """
    Oddiy baraban aylantirish.
    Natija: {reward, result_text, applied}
    """
    reward = _weighted_choice(BASIC_REWARDS)
    reward_type = reward["type"]

    # Sovg'ani qo'llash
    applied = _apply_basic_reward(user_id, reward_type)

    # Natija xabari
    result_text = _format_result(
        reward["label"],
        reward["desc"],
        applied,
        wheel_name="Oddiy Baraban",
    )

    return {
        "reward": reward,
        "result_text": result_text,
        "applied": applied,
    }


def spin_premium_wheel(user_id: int) -> dict:
    """
    Premium baraban aylantirish.
    Natija: {reward, result_text, applied}
    """
    reward = _weighted_choice(PREMIUM_REWARDS)
    reward_type = reward["type"]

    # Sovg'ani qo'llash
    applied = _apply_premium_reward(user_id, reward_type)

    # Natija xabari
    result_text = _format_result(
        reward["label"],
        reward["desc"],
        applied,
        wheel_name="Premium Baraban",
    )

    return {
        "reward": reward,
        "result_text": result_text,
        "applied": applied,
    }


def _apply_basic_reward(user_id: int, reward_type: str) -> dict:
    """Oddiy baraban sovg'asini qo'llash."""
    wheel_type = "basic"
    result = db.spin_wheel_result(user_id, wheel_type, reward_type)

    if reward_type == "coins_10":
        db.add_coins(user_id, 10, "wheel_basic_coins_10")
        result["coins_added"] = 10

    elif reward_type == "re_spin":
        # Foydalanuvchiga 1 ta bepul spin berish
        # Bu session da saqlanadi, keyin ishlatiladi
        result["free_spin_granted"] = 1

    # Boshqa sovg'alar (vocab_booster, writing_one_shot, paraphrase_day, tutor_day)
    # db.spin_wheel_result da expires_at bilan saqlanadi
    # Ular tegishli funksiyalarda tekshiriladi

    return result


def _apply_premium_reward(user_id: int, reward_type: str) -> dict:
    """Premium baraban sovg'asini qo'llash."""
    wheel_type = "premium"
    result = db.spin_wheel_result(user_id, wheel_type, reward_type)

    if reward_type == "coins_40":
        db.add_coins(user_id, 40, "wheel_premium_coins_40")
        result["coins_added"] = 40

    elif reward_type == "mega_re_spin":
        # 1 ta free spin + 5 tanga
        db.add_coins(user_id, 5, "wheel_premium_mega_re_spin_bonus")
        result["free_spin_granted"] = 1
        result["coins_added"] = 5

    # Boshqa sovg'alar (writing_pro, vocab_king, jackpot, lucky_days)
    # expires_at bilan saqlanadi

    return result


def _format_result(label: str, desc: str, applied: dict, wheel_name: str) -> str:
    """Baraban natijasini chiroyli xabar formatlash."""
    text = f"🎰 *{wheel_name} NATIJASI*\n\n"
    text += f"🎁 *Sovg'a:* {label}\n"
    text += f"📝 {desc}\n\n"

    if applied.get("coins_added"):
        text += f"💰 Balansga +{applied['coins_added']} tanga qo'shildi!\n"

    if applied.get("free_spin_granted"):
        text += "🎲 Sizga qo'shimcha aylantirish berildi!\n"

    if applied.get("expires_at"):
        from datetime import datetime
        try:
            exp = datetime.fromisoformat(applied["expires_at"].rstrip("Z"))
            text += f"⏰ Amal qilish muddati: {exp.strftime('%d.%m.%Y %H:%M')}\n"
        except (ValueError, TypeError):
            pass

    text += "\n🍀 Omadli bo'lsin! 🎉"
    return text


def check_active_wheel_reward(user_id: int, reward_type: str) -> bool:
    """Foydalanuvchida ma'lum bir wheel sovg'asi bormi tekshirish."""
    return db.has_active_reward(user_id, reward_type)


def consume_wheel_reward(user_id: int, reward_type: str) -> bool:
    """Bir martalik wheel sovg'asini ishlatish."""
    return db.consume_single_use_reward(user_id, reward_type)
