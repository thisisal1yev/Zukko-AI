"""Telegram bot: handlers and polling."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path

import telebot
from telebot import types  # pyright: ignore[reportMissingImports]

from zukko import config
from zukko import db
from zukko import prompts
from zukko.llm import ask_text_safe, ask_vision_safe
from zukko.parse_json import extract_json_blob

logger = logging.getLogger(__name__)

bot = telebot.TeleBot(config.TELEGRAM_TOKEN)


def _user_id(message: types.Message) -> int | None:
    u = message.from_user
    return int(u.id) if u else None


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SAMPLES_PATH = DATA_DIR / "samples.json"
GRAMMAR_BANK_PATH = DATA_DIR / "grammar_bank.json"

_MIN_ESSAY_LEN = 40

MENU_WRITING = lambda mode: f"✍️ {mode} Writing Tahlili"
BTN_TUTOR = "🤖 AI Tutor (Savol-javob)"
BTN_DIRECTION = "⬅️ Yo'nalish"
BTN_TEACHER = "👨‍🏫 Guruhga qo'shilish"
BTN_VOCAB = "📚 Vocabulary Booster"
BTN_PARAPHRASE = "🔁 Paraphrase o'yini"

TASK_BTN = {"📊 Task 1": "task1", "📝 Task 2": "task2", "✉️ Letter": "letter"}

IELTS_START = "🇬🇧 IELTS Yo'nalishi"
CEFR_START = "🇺🇿 CEFR (Multi-level)"

# Yangi tugmalar (tanga tizimi)
BTN_BALANCE    = "💰 Mening Tangalarim"
BTN_UPGRADE_COINS = "➕ Tanga to'ldirish"
BTN_GROUP_REPORT = "👥 Guruh Hisoboti"
BTN_PROFILE = "👤 Profil"
BTN_BACK = "🔙 Orqaga"
BTN_EXIT_GAME = "🚪 O'yindan chiqish"

# Rol tanlash tugmalari
BTN_ROLE_STUDENT = "👨‍🎓 O'quvchi"
BTN_ROLE_TEACHER = "👨‍🏫 O'qituvchi"

# O'qituvchi menyusi uchun tugmalar
BTN_CREATE_GROUP = "➕ Guruh yaratish"
BTN_MY_GROUPS = "📋 Mening guruhlarim"

_ALL_MENU_BUTTONS = frozenset(
    {
        BTN_TUTOR,
        BTN_DIRECTION,
        BTN_TEACHER,
        BTN_VOCAB,
        BTN_PARAPHRASE,
        IELTS_START,
        CEFR_START,
        BTN_BACK,
        BTN_BALANCE,
        BTN_UPGRADE_COINS,
        BTN_GROUP_REPORT,
        BTN_PROFILE,
        BTN_EXIT_GAME,
        BTN_CREATE_GROUP,
        BTN_MY_GROUPS,
    }
    | set(TASK_BTN.keys())
)


def _sess_state(message: types.Message, state: str) -> bool:
    uid = _user_id(message)
    if uid is None:
        return False
    s = db.get_session(uid)
    return bool(s and s["state"] == state)


def _is_waiting_writing(uid: int) -> bool:
    s = db.get_session(uid)
    return bool(s and s["state"] == "waiting_writing")


def _waiting_writing_filter(message: types.Message) -> bool:
    if message.content_type != "text" or not message.text:
        return False
    uid = _user_id(message)
    if uid is None:
        return False
    return _is_waiting_writing(uid)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main_menu_markup(user_id: int) -> types.ReplyKeyboardMarkup:
    """O'quvchi uchun asosiy menyu."""
    row = db.get_user_row(user_id)
    mode = row["mode"] if row else "IELTS"
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(
        MENU_WRITING(mode),
        BTN_TUTOR,
        BTN_VOCAB,
        BTN_PARAPHRASE,
        BTN_BALANCE,
        BTN_PROFILE,
        BTN_UPGRADE_COINS,
        BTN_TEACHER,
        BTN_DIRECTION,
    )
    return m


def teacher_menu_markup(user_id: int) -> types.ReplyKeyboardMarkup:
    """O'qituvchi uchun asosiy menyu."""
    row = db.get_user_row(user_id)
    mode = row["mode"] if row else "IELTS"
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(
        BTN_PROFILE,
        BTN_CREATE_GROUP,
        BTN_MY_GROUPS,
        BTN_BALANCE,
        BTN_UPGRADE_COINS,
        BTN_GROUP_REPORT,
        BTN_DIRECTION,
    )
    return m


_BLOCKED_STATES = frozenset((
    "await_teacher_id",
    "waiting_writing",
    "pick_task",
    "await_paraphrase",
    "await_vocab_topic",
    "paraphrase_payment_pick",
    "group_report_period_pick",
    "reg_ask_fullname",
    "reg_ask_phone",
    "reg_ask_role",
    "profile_edit_firstname",
    "profile_edit_lastname",
    "profile_edit_phone",
    "await_group_code",
    "await_create_group_name",
    "group_menu_idle",
))

_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def _valid_phone(phone: str) -> bool:
    return bool(_PHONE_RE.match(phone))


def task_pick_markup() -> types.ReplyKeyboardMarkup:
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    m.add("📊 Task 1", "📝 Task 2", "✉️ Letter", "🔙 Orqaga")
    return m


def _feedback_for_display(raw_reply: str, data: dict | None) -> str:
    if not raw_reply:
        return "Natija bo'sh."
    if not data:
        return raw_reply
    cut = raw_reply.rfind("{")
    if cut > 0:
        return raw_reply[:cut].strip()
    return raw_reply.strip()


def process_writing(
    chat_id: int,
    user_id: int,
    mode: str,
    task_type: str,
    input_type: str,
    transcript_source: str | None,
    image_path: str | None,
) -> None:
    # Kunlik limit tekshiruvi
    writing_today = db.get_daily_writing_count(user_id)
    row = db.get_user_row(user_id)
    role = row["role"] if row else "STUDENT"
    tariff = row["tariff"] if row else "FREE"

    # O'qituvchi PRO/PREMIUM — bepul
    if role == "TEACHER" and tariff in ("PRO", "PREMIUM"):
        cost = 0.0
    elif writing_today < config.WRITING_DAILY_FREE:
        # Kunlik bepul limit ichida
        cost = 0.0
    else:
        # Bepul limitdan keyin — to'lov
        cost = config.WRITING_EXTRA_COST
        if not db.check_coins(user_id, cost):
            bot.send_message(
                chat_id,
                f"❌ Writing tahlili uchun yetarli tanga yo'q.\n\n"
                f"💰 Kerak: {cost} tanga\n"
                f"📊 Balans: {db.get_coins(user_id):.1f} tanga\n\n"
                f"Kunlik {config.WRITING_DAILY_FREE} ta bepul tahlildingiz tugagan.",
                reply_markup=main_menu_markup(user_id),
            )
            return

    # Tanga yechish (agar pullik bo'lsa)
    if cost > 0:
        ok, balance = db.deduct_coins(user_id, cost, "writing_analysis")
        if not ok:
            bot.send_message(
                chat_id,
                f"❌ Yetarli tanga yo'q. Kerak: {cost} tanga, balans: {balance:.1f}",
                reply_markup=main_menu_markup(user_id),
            )
            return

    bot.send_message(chat_id, "🧐 AI examiner tahlil qilmoqda...")

    err_summary = db.get_error_summary_for_prompt(user_id, task_type)
    full_prompt = prompts.writing_examiner_prompt(mode, task_type, err_summary)

    if image_path and os.path.exists(image_path):
        raw = ask_vision_safe(full_prompt, image_path)
    else:
        body = transcript_source or ""
        raw = ask_text_safe(
            full_prompt
            + f"\n\nThe learner typed this essay (no image):\n---\n{body}\n---\n",
            timeout=120,
        )

    data = extract_json_blob(raw)
    transcript = (data or {}).get("transcript") if data else None
    if not transcript and transcript_source:
        transcript = transcript_source
    feedback_text = _feedback_for_display(raw, data)

    overall = None
    cefr = None
    if data:
        ob = data.get("overall_band")
        if ob is not None:
            try:
                overall = float(ob)
            except (TypeError, ValueError):
                pass
        cefr = data.get("cefr") or None

    sid = db.insert_submission(
        user_id=user_id,
        mode=mode,
        task_type=task_type,
        input_type=input_type,
        transcript=transcript or "",
        model=config.TEXT_MODEL if input_type == "text" else config.VISION_MODEL,
        scores_json=data,
        feedback_text=feedback_text,
        overall_band=overall,
        cefr_level=str(cefr) if cefr else None,
    )

    errs = (data or {}).get("errors") or []
    if isinstance(errs, list):
        clean = [e for e in errs if isinstance(e, dict)]
        db.upsert_errors(user_id, task_type, clean)

    db.record_daily_activity(user_id, met_goal=True)
    db.increment_daily_writing(user_id)
    ur = db.get_user_row(user_id)
    streak = int(ur["streak_current"] or 0) if ur else 0
    best = int(ur["streak_best"] or 0) if ur else 0

    topic = (data or {}).get("topic") or "general"
    keywords = (data or {}).get("keywords") or []
    collocations = (data or {}).get("collocations") or []
    words_pack = {
        "topic": topic,
        "keywords": keywords if isinstance(keywords, list) else [],
        "collocations": collocations if isinstance(collocations, list) else [],
        "submission_id": sid,
    }
    db.save_vocab_session(user_id, sid, str(topic), words_pack)

    db.set_session(
        user_id,
        "idle",
        {
            "last_submission_id": sid,
            "vocab": words_pack,
            "mode": mode,
            "task_type": task_type,
        },
    )

    cost_note = f"\n💰 Tanga yechildi: {cost}" if cost > 0 else ""
    footer = f"\n\n🔥 Streak: {streak} | Rekord: {best}\n📚 Vocabulary: tugmalardan foydalaning.{cost_note}"
    bot.send_message(chat_id, (feedback_text or "Tahlil.") + footer)

    demo = db.update_low_band_streak(
        user_id,
        config.LOW_BAND_THRESHOLD,
        config.LOW_BAND_STREAK_FOR_DEMO,
        overall,
    )
    if demo:
        db.mark_demo_offered(user_id)
        _send_demo_cta(chat_id)

    row_u = db.get_user_row(user_id)
    tid = row_u["teacher_id"] if row_u else None
    if tid:
        try:
            bot.send_message(
                tid,
                f"📩 Yangi yozuv (o'quvchi {user_id}):\n"
                f"Task: {task_type} | Mode: {mode}\n"
                f"Band≈{overall} | CEFR: {cefr or '-'}\n"
                f"Qisqa: {(feedback_text or '')[:400]}",
            )
        except Exception as e:
            logger.warning("teacher notify failed: %s", e)


def _send_demo_cta(chat_id: int) -> None:
    m = types.InlineKeyboardMarkup()
    has_btn = False
    if config.DEMO_LESSON_URL:
        m.add(types.InlineKeyboardButton("▶️ Demo dars", url=config.DEMO_LESSON_URL))
        has_btn = True
    if config.TEACHER_CHANNEL_URL:
        m.add(types.InlineKeyboardButton("📢 Kanal", url=config.TEACHER_CHANNEL_URL))
        has_btn = True
    text = prompts.writing_help_demo_message()
    if not has_btn:
        text += "\n\n(Kanal/demo havolalari .env orqali sozlanadi.)"
    bot.send_message(chat_id, text, reply_markup=m if has_btn else None)


@bot.message_handler(commands=["start", "help"])
def cmd_start(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return

    # Telegram ma'lumotlarini avtomatik saqlash
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    telegram_username = message.from_user.username or ""

    db.ensure_user(uid)
    db.update_user_profile(uid, first_name=first_name, last_name=last_name, telegram_username=telegram_username)

    # Agar allaqachon ro'yxatdan o'tgan bo'lsa — menyu
    if db.is_registered(uid):
        bonus_given = False
        welcome_msg = "Zukko AI Tutorga qayta xush kelibsiz!"
    else:
        # Bitta transaction da: bonus
        bonus_given = db.ensure_user_with_bonus(uid, config.INITIAL_COINS_BONUS)
        welcome_msg = (
            f"🎓 Zukko AI Tutorga xush kelibsiz, {first_name}!\n\n"
            f"To'liq ro'yxatdan o'tish uchun:\n\n"
            f"1️⃣ Ism va familiyangizni kiriting\n"
            f"2️⃣ Telefon raqamingizni 📱 Contact tugmasi orqali yuboring\n\n"
            f"Ism va familiyangizni kiriting:"
        )
        db.set_session(uid, "reg_ask_fullname", {})

    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(IELTS_START, CEFR_START)
    if not db.is_registered(uid):
        bot.send_message(message.chat.id, welcome_msg)
    else:
        if bonus_given:
            welcome_msg += f"\n\n🎁 Sizga {config.INITIAL_COINS_BONUS:.0f} tanga bonus berildi!"
        # Rolga qarab menyu ko'rsatish
        row = db.get_user_row(uid)
        role = row["role"] if row else "STUDENT"
        if role == "TEACHER":
            markup = teacher_menu_markup(uid)
        else:
            markup = main_menu_markup(uid)
        bot.send_message(message.chat.id, welcome_msg, reply_markup=markup)


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    db.clear_session(uid)
    bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_markup(uid))


# =============================================================================
# REGISTRATSIYA HANDLERLARI
# =============================================================================

def _registration_active(state: str) -> bool:
    """Registratsiya jarayonidagi state larni tekshiradi."""
    return state.startswith("reg_")


@bot.message_handler(func=lambda m: _sess_state(m, "reg_ask_fullname"))
def on_reg_fullname(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None or not message.text:
        return
    fullname = message.text.strip()
    if not fullname or len(fullname) < 3:
        bot.send_message(message.chat.id, "❌ Iltimos, ism va familiyangizni to'liq kiriting (kamida 3 ta harf):")
        return
    # Ism va familiyani ajratish
    parts = fullname.split()
    first_name = parts[0] if len(parts) > 0 else fullname
    last_name = parts[-1] if len(parts) > 1 else ""
    db.update_user_profile(uid, first_name=first_name, last_name=last_name)
    db.set_session(uid, "reg_ask_phone", {})
    # Telefon raqam share qilish tugmasi
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True))
    bot.send_message(
        message.chat.id,
        f"✅ {first_name}, endi telefon raqamingizni yuboring:\n\n"
        f"Pastdagi tugmani bosing:",
        reply_markup=kb,
    )


@bot.message_handler(content_types=["contact"], func=lambda m: _sess_state(m, "reg_ask_phone"))
def on_reg_phone_contact(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    contact = message.contact
    if not contact:
        bot.send_message(message.chat.id, "❌ Iltimos, telefon raqamingizni yuboring:")
        return
    phone = contact.phone_number
    db.update_user_profile(uid, phone=phone)
    # Rol tanlash bosqichiga o'tish
    db.set_session(uid, "reg_ask_role", {})
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(BTN_ROLE_STUDENT, callback_data="role_student"))
    kb.add(types.InlineKeyboardButton(BTN_ROLE_TEACHER, callback_data="role_teacher"))
    bot.send_message(
        message.chat.id,
        f"✅ {contact.first_name}, endi rolingizni tanlang:",
        reply_markup=kb,
    )


@bot.message_handler(
    func=lambda m: m.content_type == "text" and _sess_state(m, "reg_ask_phone")
)
def on_reg_phone_text(message: types.Message) -> None:
    """Agar foydalanuvchi contact share qilmasa, matn kiritishga ruxsat."""
    uid = _user_id(message)
    if uid is None or not message.text:
        return
    phone = message.text.strip()
    if not phone or not _valid_phone(phone):
        bot.send_message(message.chat.id, "❌ Iltimos, to'g'ri telefon raqam kiriting (masalan: +998901234567):")
        return
    db.update_user_profile(uid, phone=phone)
    # Rol tanlash bosqichiga o'tish
    db.set_session(uid, "reg_ask_role", {})
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(BTN_ROLE_STUDENT, callback_data="role_student"))
    kb.add(types.InlineKeyboardButton(BTN_ROLE_TEACHER, callback_data="role_teacher"))
    bot.send_message(
        message.chat.id,
        f"✅ Endi rolingizni tanlang:",
        reply_markup=kb,
    )


def _check_channel_subscription(user_id: int, chat_id: int) -> None:
    """
    Foydalanuvchi kanallarga obuna bo'lganligini tekshiradi.
    Agar bo'lmagan bo'lsa — obuna bo'lish tugmalarini ko'rsatadi.
    """
    if not config.PROJECT_CHANNEL or not config.SPONSOR_CHANNEL:
        # Kanal sozlanmagan bo'lsa — to'g'ridan-to'g'ri davom etish
        _complete_registration(user_id, chat_id)
        return

    # Agar avval obuna bo'lgan bo'lsa — davom etish
    if db.is_channels_subscribed(user_id):
        _complete_registration(user_id, chat_id)
        return

    # Obuna bo'lishni tekshirish
    try:
        member1 = bot.get_chat_member(f"@{config.PROJECT_CHANNEL}", user_id)
        member2 = bot.get_chat_member(f"@{config.SPONSOR_CHANNEL}", user_id)
        if member1.status in ("member", "administrator", "creator") and member2.status in ("member", "administrator", "creator"):
            db.mark_channels_subscribed(user_id)
            _complete_registration(user_id, chat_id)
            return
    except Exception as e:
        logger.warning("Channel subscription check failed: %s", e)
        # Bot kanal admini emas yoki kanal topilmadi — registratsiyani tugatish
        # Foydalanuvchini "stuck" qoldirmaslik uchun
        _complete_registration(user_id, chat_id)
        return

    # Obuna bo'lmagan — tugmalar ko'rsatish
    markup = types.InlineKeyboardMarkup()
    if config.PROJECT_CHANNEL_URL:
        markup.add(types.InlineKeyboardButton("📢 Project Kanal", url=config.PROJECT_CHANNEL_URL))
    if config.SPONSOR_CHANNEL_URL:
        markup.add(types.InlineKeyboardButton("🤝 Sponsor Kanal", url=config.SPONSOR_CHANNEL_URL))
    markup.add(types.InlineKeyboardButton("✅ Obuna bo'ldim, davom etish", callback_data="check_subscription"))

    bot.send_message(
        chat_id,
        "⚠️ Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:\n\n"
        "📢 *Project Kanal*\n"
        "🤝 *Sponsor Kanal*\n\n"
        "Obuna bo'lgach, pastdagi tugmani bosing:",
        parse_mode="Markdown",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data in ("role_student", "role_teacher"))
def on_role_select(call: types.CallbackQuery) -> None:
    """Rol tanlash callback handler."""
    uid = call.from_user.id
    role = "STUDENT" if call.data == "role_student" else "TEACHER"
    db.set_user_role(uid, role)
    db.mark_registered(uid)  # Registratsiyani tugatish
    bot.answer_callback_query(call.id, f"✅ Rol tanlandi: {'O\'quvchi' if role == 'STUDENT' else 'O\'qituvchi'}")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    # Kanal obunasini tekshirish
    _check_channel_subscription(uid, call.message.chat.id)


def _complete_registration(user_id: int, chat_id: int) -> None:
    """Registratsiyani tugallash va menyuni ko'rsatish."""
    row = db.get_user_row(user_id)
    fn = row["first_name"] if row else "Foydalanuvchi"
    role = row["role"] if row else "STUDENT"
    bonus = db.get_coins(user_id)

    # Rolga qarab menyu ko'rsatish
    if role == "TEACHER":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(IELTS_START, CEFR_START)
        bot.send_message(
            chat_id,
            f"🎉 Tabriklaymiz, {fn}! O'qituvchi sifatida ro'yxatdan o'tdingiz!\n\n"
            f"💰 Balansingiz: {bonus:.0f} tanga\n\n"
            f"Endi yo'nalishni tanlang:",
            reply_markup=kb,
        )
    else:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(IELTS_START, CEFR_START)
        bot.send_message(
            chat_id,
            f"🎉 Tabriklaymiz, {fn}! Ro'yxatdan o'tdingiz!\n\n"
            f"💰 Balansingiz: {bonus:.0f} tanga\n\n"
            f"Endi yo'nalishni tanlang:",
            reply_markup=kb,
        )


@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def on_check_subscription(call: types.CallbackQuery) -> None:
    uid = call.from_user.id

    # Agar kanallar sozlanmagan bo'lsa — to'g'ridan-to'g'ri davom etish
    if not config.PROJECT_CHANNEL or not config.SPONSOR_CHANNEL:
        db.mark_channels_subscribed(uid)
        bot.answer_callback_query(call.id, "✅ Tasdiqlandi!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        _complete_registration(uid, call.message.chat.id)
        return

    try:
        member1 = bot.get_chat_member(f"@{config.PROJECT_CHANNEL}", uid)
        member2 = bot.get_chat_member(f"@{config.SPONSOR_CHANNEL}", uid)
        if member1.status in ("member", "administrator", "creator") and member2.status in ("member", "administrator", "creator"):
            db.mark_channels_subscribed(uid)
            bot.answer_callback_query(call.id, "✅ Obuna tasdiqlandi!")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            _complete_registration(uid, call.message.chat.id)
        else:
            # Qaysi kanallarga obuna bo'lmaganini aniqlash
            not_subscribed = []
            if member1.status not in ("member", "administrator", "creator"):
                not_subscribed.append(f"@{config.PROJECT_CHANNEL}")
            if member2.status not in ("member", "administrator", "creator"):
                not_subscribed.append(f"@{config.SPONSOR_CHANNEL}")
            
            # Aniq xabar
            channels_str = " va ".join(not_subscribed)
            suffix = "lariga" if len(not_subscribed) > 1 else "iga"
            bot.answer_callback_query(
                call.id, 
                f"❌ Siz {channels_str} kanal{suffix} obuna bo'lmagansiz!", 
                show_alert=True
            )
    except Exception as e:
        error_msg = str(e)
        logger.warning("Subscription check callback failed: %s", e)

        # Agar kanal topilmasa — foydalanuvchiga aniq xabar
        if "chat not found" in error_msg.lower() or "bad request" in error_msg.lower():
            # Fallback: qo'lda tasdiqlash tugmasi
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ Men obuna bo'ldim (tasdiqlash)", callback_data="confirm_subscribed_manual"))
            bot.send_message(
                call.message.chat.id,
                "⚠️ Kanallar tekshirishda xatolik yuz berdi.\n\n"
                "Iltimos, quyidagi kanallarga obuna bo'ling:\n"
                f"📢 {config.PROJECT_CHANNEL_URL}\n"
                f"🤝 {config.SPONSOR_CHANNEL_URL}\n\n"
                "Obuna bo'lgach, pastdagi tugmani bosing:",
                reply_markup=markup,
            )
            bot.answer_callback_query(call.id, "⚠️ Kanal topilmadi. Qo'lda tasdiqlang.", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Xatolik yuz berdi. Qayta urinib ko'ring.", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data == "confirm_subscribed_manual")
def on_manual_subscription_confirm(call: types.CallbackQuery) -> None:
    """Foydalanuvchi qo'lda tasdiqlaganda."""
    uid = call.from_user.id
    db.mark_channels_subscribed(uid)
    bot.answer_callback_query(call.id, "✅ Tasdiqlandi!")
    # Barcha kanal xabarlarini o'chirish
    bot.delete_message(call.message.chat.id, call.message.message_id)
    _complete_registration(uid, call.message.chat.id)


def _direction_filter(message: types.Message) -> bool:
    if not message.text:
        return False
    t = message.text
    uid = _user_id(message)
    if uid and not db.is_registered(uid):
        bot.send_message(message.chat.id, "⚠️ Avval ro'yxatdan o'ting. /start ni bosing.")
        return False
    return t == BTN_DIRECTION or t in (IELTS_START, CEFR_START)


@bot.message_handler(func=_direction_filter)
def on_direction(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if message.text == BTN_DIRECTION:
        m = types.ReplyKeyboardMarkup(resize_keyboard=True)
        m.add(IELTS_START, CEFR_START)
        bot.send_message(message.chat.id, "Yo'nalishni qayta tanlang:", reply_markup=m)
        return
    text = message.text
    if not text:
        return
    mode = "IELTS" if text == IELTS_START else "CEFR"
    db.ensure_user(uid)
    db.set_user_mode(uid, mode)
    # Rolga qarab menyu ko'rsatish
    row = db.get_user_row(uid)
    role = row["role"] if row else "STUDENT"
    if role == "TEACHER":
        bot.send_message(
            message.chat.id,
            f"✅ {mode} rejasi faollashdi!",
            reply_markup=teacher_menu_markup(uid),
        )
    else:
        bot.send_message(
            message.chat.id,
            f"✅ {mode} rejasi faollashdi!",
            reply_markup=main_menu_markup(uid),
        )


def _starts_writing(text: str) -> bool:
    return text.startswith("✍️") and "Writing" in text


def _check_channel_or_block(uid: int, chat_id: int) -> bool:
    """
    Kanal obunasini tekshiradi. Agar bo'lmasa — xabar yuboradi va False qaytaradi.
    Agar bo'lsa yoki kanal sozlanmagan bo'lsa — True qaytaradi.
    """
    if not config.PROJECT_CHANNEL or not config.SPONSOR_CHANNEL:
        return True
    if db.is_channels_subscribed(uid):
        return True
    # Qayta tekshirish
    try:
        member1 = bot.get_chat_member(f"@{config.PROJECT_CHANNEL}", uid)
        member2 = bot.get_chat_member(f"@{config.SPONSOR_CHANNEL}", uid)
        if member1.status in ("member", "administrator", "creator") and member2.status in ("member", "administrator", "creator"):
            db.mark_channels_subscribed(uid)
            return True
    except Exception:
        pass
    # Obuna bo'lmagan — tugma ko'rsatish
    markup = types.InlineKeyboardMarkup()
    if config.PROJECT_CHANNEL_URL and "project" in not_subscribed:
        markup.add(types.InlineKeyboardButton("📢 Project Kanal", url=config.PROJECT_CHANNEL_URL))
    if config.SPONSOR_CHANNEL_URL and True:
        markup.add(types.InlineKeyboardButton("🤝 Sponsor Kanal", url=config.SPONSOR_CHANNEL_URL))
    markup.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_subscription"))
    bot.send_message(
        chat_id,
        "⚠️ Botdan foydalanish uchun kanallarga obuna bo'ling:\n\n"
        "Obuna bo'lgach, pastdagi tugmani bosing:",
        reply_markup=markup,
    )
    return False


@bot.message_handler(func=lambda m: bool(m.text and _starts_writing(m.text)))
def on_writing_menu(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not _check_channel_or_block(uid, message.chat.id):
        return
    bot.send_message(
        message.chat.id,
        "Writing uchun task turini tanlang (IELTS Task 1/2 yoki Letter):",
        reply_markup=task_pick_markup(),
    )
    db.set_session(uid, "pick_task", {})


@bot.message_handler(
    func=lambda m: bool(
        m.text and (m.text in TASK_BTN or (m.text == "🔙 Orqaga" and _sess_state(m, "pick_task")))
    )
)
def on_task_pick(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    mt = message.text
    if mt == "🔙 Orqaga":
        db.clear_session(uid)
        bot.send_message(message.chat.id, "Menyu:", reply_markup=main_menu_markup(uid))
        return
    if mt is None or mt not in TASK_BTN:
        return
    task = TASK_BTN[mt]
    db.set_preferred_task(uid, task)
    db.set_session(uid, "waiting_writing", {"task_type": task})
    bot.send_message(
        message.chat.id,
        "Rasm yuboring (handwriting) yoki inshoni matn ko'rinishida yozing.",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(content_types=["photo"])
def on_photo(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    db.ensure_user(uid)
    if not db.is_registered(uid):
        bot.send_message(message.chat.id, "⚠️ Avval ro'yxatdan o'ting. /start ni bosing.")
        return
    if not _check_channel_or_block(uid, message.chat.id):
        return
    row = db.get_user_row(uid)
    mode = row["mode"] if row else "IELTS"
    sess = db.get_session(uid)
    state = sess["state"] if sess else None
    task_type = row["preferred_task"] if row else "task2"
    if state == "waiting_writing" and sess:
        ctx = db.session_context(uid)
        task_type = ctx.get("task_type") or task_type

    path: str | None = None
    try:
        bot.send_message(message.chat.id, "🧐 AI examiner tahlil qilmoqda...")
        photos = message.photo
        if not photos:
            bot.send_message(message.chat.id, "⚠️ Rasm topilmadi.")
            return
        fi = bot.get_file(photos[-1].file_id)
        fp = fi.file_path
        if fp is None:
            bot.send_message(message.chat.id, "⚠️ Fayl yo'li mavjud emas.")
            return
        data = bot.download_file(fp)
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(data)
        process_writing(message.chat.id, uid, mode, task_type, "image", None, path)
    except Exception as e:
        logger.exception("photo fail: %s", e)
        bot.send_message(message.chat.id, "⚠️ Xatolik yuz berdi.")
    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


@bot.message_handler(func=_waiting_writing_filter)
def on_essay_text(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    raw = message.text
    if raw is None:
        return
    text = raw.strip()
    if text == "🔙 Orqaga":
        db.clear_session(uid)
        bot.send_message(message.chat.id, "Writing bekor qilindi.", reply_markup=main_menu_markup(uid))
        return
    if len(text) < _MIN_ESSAY_LEN:
        bot.send_message(
            message.chat.id,
            f"Insho juda qisqa (min ~{_MIN_ESSAY_LEN} belgi). Davom eting yoki rasm yuboring.",
        )
        return
    row = db.get_user_row(uid)
    mode = row["mode"] if row else "IELTS"
    ctx = db.session_context(uid)
    task_type = ctx.get("task_type") or (row["preferred_task"] if row else "task2")
    process_writing(message.chat.id, uid, mode, task_type, "text", text, None)


@bot.message_handler(func=lambda m: m.text == BTN_TUTOR)
def on_tutor_hint(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not _check_channel_or_block(uid, message.chat.id):
        return
    bot.send_message(message.chat.id, "Savolingizni yozing — ingliz tili o'qituvchisi sifatida javob beraman.")


@bot.message_handler(func=lambda m: m.text == BTN_TEACHER)
def on_teacher_link(message: types.Message) -> None:
    """O'quvchi uchun: guruhga qo'shilish (kod kiritish)."""
    uid = _user_id(message)
    if uid is None:
        return
    row = db.get_user_row(uid)
    role = row["role"] if row else "STUDENT"

    # Agar o'qituvchi bo'lsa — guruh yaratishga yo'naltirish
    if role == "TEACHER":
        on_create_group_menu(message)
        return

    # O'quvchi — allaqachon guruhda bo'lsa
    user_dict = dict(row)
    group_id = user_dict.get("group_id")
    if group_id:
        group = db.get_group_by_id(group_id)
        if group:
            teacher = db.get_user_row(group["teacher_id"])
            teacher_name = teacher["first_name"] if teacher and teacher["first_name"] else "O'qituvchi"
            bot.send_message(
                message.chat.id,
                f"🏫 Siz allaqachon guruhdasiz:\n\n"
                f"📌 Guruh: <b>{group['name']}</b>\n"
                f"👨‍🏫 O'qituvchi: <b>{teacher_name}</b>\n"
                f"🔑 Kod: <code>{group['join_code']}</code>",
                parse_mode="HTML",
                reply_markup=main_menu_markup(uid),
            )
            return

    # Guruhga qo'shilish — kod kiritish
    db.set_session(uid, "await_group_code", {})
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(BTN_BACK)
    bot.send_message(
        message.chat.id,
        "🏫 <b>Guruhga qo'shilish</b>\n\n"
        "O'qituvchingiz bergan <b>qo'shilish kodini</b> kiriting:\n\n"
        "(Masalan: ABC12345)",
        parse_mode="HTML",
        reply_markup=kb,
    )


@bot.message_handler(
    func=lambda m: m.content_type == "text" and _sess_state(m, "await_group_code")
)
def on_group_code_submit(message: types.Message) -> None:
    """O'quvchi guruh kodini kiritganda."""
    uid = _user_id(message)
    if uid is None:
        return
    if not message.text:
        return
    if message.text.strip() == BTN_BACK:
        db.clear_session(uid)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_markup(uid))
        return

    code = message.text.strip().upper()
    group = db.get_group_by_code(code)

    if not group:
        bot.send_message(
            message.chat.id,
            "❌ Bunday kodli guruh topilmadi. Qayta urinib ko'ring:",
        )
        return

    # Guruhga qo'shish
    db.set_group_id(uid, group["id"])
    db.set_teacher_id(uid, group["teacher_id"])
    db.clear_session(uid)

    teacher = db.get_user_row(group["teacher_id"])
    teacher_name = teacher["first_name"] if teacher and teacher["first_name"] else "O'qituvchi"

    bot.send_message(
        message.chat.id,
        f"✅ Guruhga qo'shildingiz!\n\n"
        f"📌 Guruh: <b>{group['name']}</b>\n"
        f"👨‍🏫 O'qituvchi: <b>{teacher_name}</b>",
        parse_mode="HTML",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(
    func=lambda m: m.text == BTN_BACK and _sess_state(m, "await_group_code")
)
def on_group_code_back(message: types.Message) -> None:
    """Guruh kodini bekor qilish."""
    uid = _user_id(message)
    if uid is None:
        return
    db.clear_session(uid)
    bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_markup(uid))


def _fallback_allowed(message: types.Message) -> bool:
    if message.content_type != "text" or not message.text:
        return False
    t = message.text
    if t in _ALL_MENU_BUTTONS or t in TASK_BTN:
        return False
    if _starts_writing(t):
        return False
    uid = _user_id(message)
    if uid is None:
        return False
    sess = db.get_session(uid)
    if sess and sess["state"] in _BLOCKED_STATES:
        return False
    return True


@bot.message_handler(func=_fallback_allowed)
def on_fallback_text(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not _check_channel_or_block(uid, message.chat.id):
        return
    q = message.text
    if not q:
        return
    row = db.get_user_row(uid)
    mode = row["mode"] if row else "IELTS"
    bot.send_chat_action(message.chat.id, "typing")
    res = ask_text_safe(f"Ingliz tili o'qituvchisi sifatida ({mode} kontekstida) javob ber: {q}")
    bot.reply_to(message, res)


# =============================================================================
# YANGI HANDLERLAR: Tanga, Vocabulary, Paraphrase, Guruh Hisoboti
# =============================================================================

@bot.message_handler(func=lambda m: m.text == BTN_BALANCE)
def on_balance(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not _check_channel_or_block(uid, message.chat.id):
        return
    coins = db.get_coins(uid)
    row = db.get_user_row(uid)
    role = row["role"] if row else "STUDENT"
    tariff = row["tariff"] if row else "FREE"
    writing_today = db.get_daily_writing_count(uid)
    paraphrase_today = db.get_daily_paraphrase_count(uid)
    combo = row["combo_streak"] if row else 0
    free = row["free_spins"] if row else 0

    # O'qituvchi uchun qo'shimcha ma'lumot
    extra_msg = ""
    if role == "TEACHER":
        groups = db.get_teacher_groups(uid)
        if groups:
            total_students = 0
            for g in groups:
                students = db.get_group_students(g["id"])
                total_students += len(students)
            extra_msg = f"\n\n👨‍🏫 *Guruhlar*: {len(groups)} ta\n" \
                        f"👥 *Jami o'quvchilar*: {total_students} ta"

    msg = (
        f"💰 *Tanga hisobingiz*: `{coins:.1f}`\n\n"
        f"🎫 *Tarif*: {tariff}\n"
        f"{extra_msg}\n"
        f"📊 *Bugungi limitlar*:\n"
        f"• Writing tahlili: {writing_today}/{config.WRITING_DAILY_FREE} (bepul)\n"
        f"• Paraphrase o'yini: {paraphrase_today}/{config.PARAPHRASE_DAILY_FREE} (bepul)\n\n"
        f"🔥 *Combo*: {combo} ketma-ket\n"
        f"🎰 *Tekin barabanlar*: {free}\n\n"
        f"💵 *Narxlar*:\n"
        f"• Writing tahlili: {config.WRITING_ANALYSIS_COST} tanga (bepul limitdan keyin)\n"
        f"• Vocabulary: {config.VOCAB_COST} tanga\n"
        f"• Paraphrase: {config.PARAPHRASE_COST} tanga"
    )
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == BTN_UPGRADE_COINS)
def on_topup(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    markup = types.InlineKeyboardMarkup()
    # Bu yerda to'lov havolasi bo'ladi
    markup.add(types.InlineKeyboardButton("💳 To'lov sahifasi (tez orada)", url="https://t.me/thisisaliyev"))
    bot.send_message(
        message.chat.id,
        "Tanga to'ldirish uchun pastdagi tugmani bosing yoki admin bilan bog'laning.\n\n"
        "💰 *1000 tanga = 10,000 so'm*",
        parse_mode="Markdown",
        reply_markup=markup,
    )


# =============================================================================
# O'QITUVCHI: GURUH YARATISH
# =============================================================================

def on_create_group_menu(message: types.Message) -> None:
    """O'qituvchi uchun guruh yaratish menyusi."""
    uid = _user_id(message)
    if uid is None:
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(BTN_CREATE_GROUP, BTN_MY_GROUPS)
    kb.add(BTN_BACK)
    db.set_session(uid, "group_menu_idle", {})
    bot.send_message(
        message.chat.id,
        "👨‍🏫 <b>Guruhlar boshqaruvi</b>\n\n"
        "➕ Yangi guruh yaratish yoki\n"
        "📋 Mavjud guruh'laringizni ko'rish:",
        parse_mode="HTML",
        reply_markup=kb,
    )


@bot.message_handler(func=lambda m: m.text == BTN_CREATE_GROUP)
def on_create_group(message: types.Message) -> None:
    """Guruh yaratishni boshlash."""
    uid = _user_id(message)
    if uid is None:
        return
    row = db.get_user_row(uid)
    role = row["role"] if row else "STUDENT"
    if role != "TEACHER":
        bot.send_message(
            message.chat.id,
            "❌ Bu funksiya faqat o'qituvchilar uchun.",
            reply_markup=main_menu_markup(uid),
        )
        return
    db.set_session(uid, "await_create_group_name", {})
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(BTN_BACK)
    bot.send_message(
        message.chat.id,
        "➕ <b>Yangi guruh yaratish</b>\n\n"
        "Guruh nomini kiriting:\n"
        "(Masalan: IELTS Advanced A1)",
        parse_mode="HTML",
        reply_markup=kb,
    )


@bot.message_handler(
    func=lambda m: m.content_type == "text" and _sess_state(m, "await_create_group_name")
)
def on_group_name_submit(message: types.Message) -> None:
    """O'qituvchi guruh nomini kiritganda."""
    uid = _user_id(message)
    if uid is None:
        return
    if not message.text:
        return
    if message.text.strip() == BTN_BACK:
        db.clear_session(uid)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=teacher_menu_markup(uid))
        return

    name = message.text.strip()
    if len(name) < 2:
        bot.send_message(message.chat.id, "❌ Guruh nomi kamida 2 ta harf bo'lishi kerak:")
        return

    # Guruh yaratish
    group = db.create_group(name, uid)

    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        f"✅ Guruh muvaffaqiyatli yaratildi!\n\n"
        f"📌 Guruh: <b>{group['name']}</b>\n"
        f"🔑 Qo'shilish kodi: <code>{group['join_code']}</code>\n\n"
        f"Bu kodni o'quvchilaringizga yuboring. Ular shu kod orqali guruhga qo'shilishadi.",
        parse_mode="HTML",
        reply_markup=teacher_menu_markup(uid),
    )


@bot.message_handler(func=lambda m: m.text == BTN_MY_GROUPS)
def on_my_groups(message: types.Message) -> None:
    """O'qituvchining guruhlarini ko'rsatish."""
    uid = _user_id(message)
    if uid is None:
        return
    groups = db.get_teacher_groups(uid)
    if not groups:
        bot.send_message(
            message.chat.id,
            "📋 Sizda hali guruhlar yo'q.\n\n"
            "➕ Yangi guruh yaratish uchun pastdagi tugmani bosing:",
            reply_markup=teacher_menu_markup(uid),
        )
        return

    text = "📋 <b>Mening guruhlarim:</b>\n\n"
    for g in groups:
        students = db.get_group_students(g["id"])
        text += (
            f"📌 <b>{g['name']}</b>\n"
            f"🔑 Kod: <code>{g['join_code']}</code>\n"
            f"👥 O'quvchilar: {len(students)} ta\n\n"
        )

    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=teacher_menu_markup(uid))


# ── Profil ────────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == BTN_PROFILE)
def on_profile(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        logger.warning("Profile: uid is None")
        return
    row = db.get_user_row(uid)
    if not row:
        logger.warning("Profile: user not found for uid=%d", uid)
        bot.send_message(message.chat.id, "⚠️ Foydalanuvchi topilmadi. /start ni bosing.")
        return

    fn = row["first_name"] or "—"
    ln = row["last_name"] or "—"
    phone = row["phone"] or "—"
    tg_username = row["telegram_username"] or "—"
    mode = row["mode"] or "IELTS"
    tariff = row["tariff"] or "FREE"
    coins = row["coins"] if row["coins"] is not None else 0
    role = row["role"] if row else "STUDENT"

    # O'quvchi uchun: guruh va o'qituvchi ma'lumotlari
    extra_info = ""
    if role == "STUDENT":
        # Guruh ma'lumotlari
        user_dict = dict(row)
        group_id = user_dict.get("group_id")
        if group_id:
            group = db.get_group_by_id(group_id)
            if group:
                extra_info += f"\n🏫 Guruh: <b>{group['name']}</b>"
                # O'qituvchi ismi
                teacher = db.get_user_row(group["teacher_id"])
                if teacher:
                    teacher_name = teacher["first_name"] or "O'qituvchi"
                    teacher_last = teacher["last_name"] or ""
                    full_teacher = f"{teacher_name} {teacher_last}".strip()
                    extra_info += f"\n👨‍🏫 O'qituvchi: <b>{full_teacher}</b>"
        else:
            extra_info += "\n🏫 Guruh: <i>Hali guruhga qo'shilmagansiz</i>"

    text = (
        f"👤 <b>PROFILINGIZ</b>\n\n"
        f"👤 Ism: <b>{fn}</b>\n"
        f"👤 Familiya: <b>{ln}</b>\n"
        f"📱 Telefon: <code>{phone}</code>\n"
        f"🔗 Telegram username: @{tg_username}\n\n"
        f"🎫 Tarif: {tariff}\n"
        f"💰 Tanga: {coins:.0f}\n"
        f"📚 Rejim: {mode}"
        f"{extra_info}"
        f"\n\n✏️ <b>Tahrirlash:</b>\n"
        f"/edit_name — Ism o'zgartirish\n"
        f"/edit_lastname — Familiya o'zgartirish\n"
        f"/edit_phone — Telefon o'zgartirish"
    )
    logger.info("Profile shown for uid=%d", uid)
    bot.send_message(message.chat.id, text, parse_mode="HTML")


@bot.message_handler(commands=["edit_name"])
def on_edit_firstname(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not db.is_registered(uid):
        bot.send_message(message.chat.id, "⚠️ Avval ro'yxatdan o'ting. /start ni bosing.")
        return
    db.set_session(uid, "profile_edit_firstname", {})
    bot.send_message(message.chat.id, "✏️ Yangi ismingizni kiriting:")


@bot.message_handler(func=lambda m: _sess_state(m, "profile_edit_firstname"))
def on_profile_edit_firstname(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None or not message.text:
        return
    new_name = message.text.strip()
    if not new_name or len(new_name) < 2:
        bot.send_message(message.chat.id, "❌ Ism kamida 2 ta harf bo'lishi kerak:")
        return
    db.update_user_profile(uid, first_name=new_name)
    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        f"✅ Ismingiz o'zgartirildi: <b>{new_name}</b>",
        parse_mode="HTML",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(commands=["edit_lastname"])
def on_edit_lastname(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not db.is_registered(uid):
        bot.send_message(message.chat.id, "⚠️ Avval ro'yxatdan o'ting. /start ni bosing.")
        return
    db.set_session(uid, "profile_edit_lastname", {})
    bot.send_message(message.chat.id, "✏️ Yangi familiyangizni kiriting:")


@bot.message_handler(func=lambda m: _sess_state(m, "profile_edit_lastname"))
def on_profile_edit_lastname(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None or not message.text:
        return
    new_lastname = message.text.strip()
    if not new_lastname or len(new_lastname) < 2:
        bot.send_message(message.chat.id, "❌ Familiya kamida 2 ta harf bo'lishi kerak:")
        return
    db.update_user_profile(uid, last_name=new_lastname)
    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        f"✅ Familiyangiz o'zgartirildi: <b>{new_lastname}</b>",
        parse_mode="HTML",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(commands=["edit_phone"])
def on_edit_phone(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not db.is_registered(uid):
        bot.send_message(message.chat.id, "⚠️ Avval ro'yxatdan o'ting. /start ni bosing.")
        return
    # Contact share tugmasi
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True))
    kb.add(BTN_BACK)
    db.set_session(uid, "profile_edit_phone", {})
    bot.send_message(
        message.chat.id,
        "✏️ Yangi telefon raqamingizni yuboring:",
        reply_markup=kb,
    )


@bot.message_handler(content_types=["contact"], func=lambda m: _sess_state(m, "profile_edit_phone"))
def on_profile_edit_phone_contact(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    contact = message.contact
    if not contact:
        bot.send_message(message.chat.id, "❌ Iltimos, telefon raqamingizni yuboring:")
        return
    phone = contact.phone_number
    db.update_user_profile(uid, phone=phone)
    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        f"✅ Telefon raqamingiz o'zgartirildi: <code>{phone}</code>",
        parse_mode="HTML",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(
    func=lambda m: m.content_type == "text" and _sess_state(m, "profile_edit_phone")
)
def on_profile_edit_phone_text(message: types.Message) -> None:
    """Agar foydalanuvchi contact share qilmasa, matn kiritishga ruxsat."""
    uid = _user_id(message)
    if uid is None or not message.text:
        return
    if message.text.strip() == BTN_BACK:
        db.clear_session(uid)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_markup(uid))
        return
    phone = message.text.strip()
    if not phone or not _valid_phone(phone):
        bot.send_message(message.chat.id, "❌ Iltimos, to'g'ri telefon raqam kiriting (masalan: +998901234567):")
        return
    db.update_user_profile(uid, phone=phone)
    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        f"✅ Telefon raqamingiz o'zgartirildi: <code>{phone}</code>",
        parse_mode="HTML",
        reply_markup=main_menu_markup(uid),
    )


# ── Paraphrase o'yini ──────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == BTN_PARAPHRASE)
def on_paraphrase_menu(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not _check_channel_or_block(uid, message.chat.id):
        return
    db.ensure_user(uid)
    db.reset_daily_limits_if_needed(uid)

    # 1. Foydalanuvchining essaylari borligini tekshirish
    essays = db.get_transcripts_for_paraphrase(uid)
    if not essays:
        # Essay yo'q — Writing bo'limiga yo'naltirish
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(MENU_WRITING(db.get_user_row(uid)["mode"] if db.get_user_row(uid) else "IELTS"))
        markup.add(BTN_BACK)
        bot.send_message(
            message.chat.id,
            "⚠️ *Paraphrase o'yini* uchun sizga avval kamida bitta essay yozish kerak!\n\n"
            "📝 Siz hali birorta ham writing tahlil qildirmagansiz.\n\n"
            "Iltimos, avval *✍️ Writing Tahlili* bo'limidan o'z esseingizni yuboring. "
            "AI uni tahlil qilgandan so'ng, essayingizdan jumla yoki so'zlar olib, "
            "paraphrase o'ynash mumkin bo'ladi.\n\n"
            "👇 Pastdagi tugmani bosib Writing bo'limiga o'ting:",
            parse_mode="Markdown",
            reply_markup=markup,
        )
        return

    # 2. Essay bor — AI dan eng yaxshi jumlani tanlab olish
    bot.send_message(message.chat.id, "🔁 Paraphrase o'yini — essayingizdan jumla tanlanmoqda...")

    # Eng oxirgi essay dan foydalanamiz
    latest_essay = essays[0]
    essay_text = latest_essay["transcript"]

    sys_prompt = prompts.paraphrase_extract_sentence_prompt(essay_text)
    raw = ask_text_safe(sys_prompt, timeout=60)
    data = extract_json_blob(raw)

    sentence = (data or {}).get("sentence", "")
    reason = (data or {}).get("reason", "")

    # Agar AI jumla topa olmasa, fallback: birinchi uzunroq jumla
    if not sentence:
        import re
        sentences = re.split(r'(?<=[.!?])\s+', essay_text)
        for s in sentences:
            if len(s) > 30 and len(s) < 200:
                sentence = s
                break
        if not sentence and sentences:
            sentence = sentences[0]

    if not sentence:
        bot.send_message(
            message.chat.id,
            "❌ Essayingizdan paraphrase qilish uchun jumla topilmadi. "
            "Iltimos, batafsilroq essay yozib qayta urinib ko'ring.",
            reply_markup=main_menu_markup(uid),
        )
        return

    # 3. Paraphrase o'yinini boshlash
    paraphrase_count = db.get_daily_paraphrase_count(uid)
    row = db.get_user_row(uid)
    free_spins = row["free_spins"] if row else 0
    combo = row["combo_streak"] if row else 0

    # Agar bepul limitdan oshgan bo'lsa, to'lash kerak
    if paraphrase_count >= config.PARAPHRASE_DAILY_FREE:
        cost = config.PARAPHRASE_COST
        if free_spins > 0:
            # Tekin baraban bor
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("🎰 Tekin baraban ishlatish", BTN_BACK)
            bot.send_message(
                message.chat.id,
                f"🎰 Sizda {free_spins} ta tekin baraban bor!\n\n"
                f"Combo: {combo}\n\n"
                f"Yoki {cost} tanga to'lab davom eting.",
                reply_markup=markup,
            )
            db.set_session(uid, "paraphrase_payment_pick", {})
            return
        # To'lash kerak
        if not db.check_coins(uid, cost):
            bot.send_message(
                message.chat.id,
                f"❌ Kechirasiz, bugungi bepul limit ({config.PARAPHRASE_DAILY_FREE} ta) tugagan.\n\n"
                f"💰 Paraphrase narxi: {cost} tanga\n"
                f"📊 Sizning balansingiz: {db.get_coins(uid):.1f} tanga\n\n"
                f"Iltimos, hisobni to'ldiring.",
                reply_markup=main_menu_markup(uid),
            )
            return

    # 4. Sessiyaga asl jumlani saqlash va foydalanuvchiga taklif
    db.set_session(uid, "await_paraphrase", {
        "original_sentence": sentence,
        "essay_topic": latest_essay.get("topic", ""),
        "extract_reason": reason,
    })
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(BTN_EXIT_GAME)

    topic_info = ""
    if latest_essay.get("topic"):
        topic_info = f"📚 Mavzu: {latest_essay['topic']}\n"

    bot.send_message(
        message.chat.id,
        f"🔁 *Paraphrase o'yini*\n\n"
        f"{topic_info}"
        f"📝 *Sizning essayingizdan jumla:*\n\"{sentence}\"\n\n"
        f"💡 _{reason}_\n\n"
        f"Endi shu jumlani *o'z so'zlaringiz bilan qayta yozing* (paraphrase qiling). "
        f"AI ma'no saqlanganmi, tabiiylik darajasi va yaxshiroq variantni baholaydi.\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 Narx: {config.PARAPHRASE_COST} tanga (bepul limitdan keyin)\n"
        f"🔥 Combo: {combo} ketma-ket\n"
        f"🎰 Tekin barabanlar: {free_spins}\n"
        f"📊 Bugungi: {paraphrase_count}/{config.PARAPHRASE_DAILY_FREE} (bepul)\n\n"
        f"✍️ Paraphrase variantni yozing:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@bot.message_handler(func=lambda m: m.text == "🎰 Tekin baraban ishlatish" and _sess_state(m, "paraphrase_payment_pick"))
def on_free_spin_use(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if db.use_free_spin(uid):
        db.set_session(uid, "await_paraphrase", {})
        bot.send_message(
            message.chat.id,
            "🎰 Tekin baraban ishlatildi! Paraphrase qilmoqchi bo'lgan jumlani yozing:",
            reply_markup=main_menu_markup(uid),
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ Kechirasiz, tekin barabanlar tugagan.",
            reply_markup=main_menu_markup(uid),
        )


@bot.message_handler(func=lambda m: m.text == BTN_EXIT_GAME and _sess_state(m, "await_paraphrase"))
def on_paraphrase_exit(message: types.Message) -> None:
    """O'yindan chiqish."""
    uid = _user_id(message)
    if uid is None:
        return
    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        "🚪 O'yindan chiqdingiz.",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(
    func=lambda m: m.content_type == "text"
    and _sess_state(m, "await_paraphrase")
    and m.text not in _ALL_MENU_BUTTONS
)
def on_paraphrase_submit(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    user_rewrite = message.text.strip()
    if not user_rewrite:
        return

    # Session context dan asl jumlani olish (AI tomonidan essay dan tanlab olingan)
    ctx = db.session_context(uid)
    original = ctx.get("original_sentence")

    if not original:
        # Bu eski logika fallback — agar session da original bo'lmasa
        # Bu holat endi kutilmaydi, lekin xavfsizlik uchun qoldiriladi
        db.update_session_context(uid, original_sentence=user_rewrite)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        kb.add(BTN_EXIT_GAME)
        bot.send_message(
            message.chat.id,
            "✅ Endi shu jumlani paraphrase qiling (o'z so'zlaringiz bilan qayta yozing):",
            reply_markup=kb,
        )
        return

    # Foydalanuvchi paraphrase qildi — baholash
    paraphrase_count = db.get_daily_paraphrase_count(uid)
    row = db.get_user_row(uid)
    free_spins = row["free_spins"] if row else 0

    # To'lov tekshiruvi
    if paraphrase_count >= config.PARAPHRASE_DAILY_FREE:
        if free_spins > 0:
            db.use_free_spin(uid)
        else:
            cost = config.PARAPHRASE_COST
            ok, balance = db.deduct_coins(uid, cost, "paraphrase")
            if not ok:
                bot.send_message(
                    message.chat.id,
                    f"❌ Yetarli tanga yo'q. Kerak: {cost} tanga, balans: {balance:.1f}",
                    reply_markup=main_menu_markup(uid),
                )
                db.clear_session(uid)
                return

    # Baholash
    sys_prompt = prompts.paraphrase_judge_detailed_prompt(original, user_rewrite)
    raw = ask_text_safe(sys_prompt, timeout=90)
    data = extract_json_blob(raw)

    # Natijani formatlash
    score = (data or {}).get("score", 0)
    verdict = (data or {}).get("verdict", "average")
    positive = (data or {}).get("positive", "")
    needs_improvement = (data or {}).get("needs_improvement", "")
    ideal = (data or {}).get("ideal_variant", "")

    verdict_emoji = {
        "good": "✅ Yaxshi",
        "average": "🟡 O'rtacha",
        "weak": "❌ Zaif",
    }.get(verdict, "🟡 O'rtacha")

    # Combo yangilash
    meaning_preserved = (data or {}).get("meaning_preserved", False)
    streak_broken = score < 7

    if streak_broken:
        # Combo buzildi — 0 ga tushadi
        db.reset_combo_streak(uid)
        new_combo = 0
        reward = 0.0
        combo_msg = "\n💔 Combo buzildi! Combo 0 ga tushdi."
    else:
        # Combo davom etadi
        _, earned_spin = db.update_combo_streak(uid, increment=True)
        row_after = db.get_user_row(uid)
        new_combo = int(row_after["combo_streak"]) if row_after and row_after["combo_streak"] is not None else 0
        earned_spin = int(row_after["free_spins"]) if row_after and row_after["free_spins"] is not None else 0
        # Tanga mukofoti
        reward = db.get_paraphrase_reward(new_combo)
        if reward > 0:
            db.add_coins(uid, reward, "paraphrase_reward")
            combo_msg = f"\n💰 +{reward:.1f} tanga mukofot!"
        else:
            combo_msg = ""
        if earned_spin > 0:
            combo_msg += f"\n🎉 +{earned_spin} ta tekin baraban qozonildi!"

    spin_msg = ""
    row_final = db.get_user_row(uid)
    free_final = int(row_final["free_spins"]) if row_final and row_final["free_spins"] is not None else 0
    if free_final > 0:
        spin_msg = f"\n🎰 Tekin barabanlar: {free_final}"

    result_text = (
        f"🎮 *PARAPHRASE NATIJASI*\n\n"
        f"Asl jumla: \"{original}\"\n"
        f"Sizning variant: \"{user_rewrite}\"\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Ball: {score} / 10\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"{verdict_emoji}\n\n"
        f"📝 Izoh:\n"
        f"• {positive}\n"
        f"• {needs_improvement}\n\n"
        f"💡 Ideal variant: \"{ideal}\"\n\n"
        f"🔥 Combo: {new_combo} ketma-ket"
        f"{combo_msg}"
        f"{spin_msg}"
    )

    db.increment_daily_paraphrase(uid)
    # Keyingi savol uchun sessiyani saqlab qolish, chiqish tugmasini ko'rsatish
    db.set_session(uid, "await_paraphrase", {"original_sentence": original})
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(BTN_EXIT_GAME)
    bot.send_message(
        message.chat.id,
        result_text,
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ── Vocabulary Booster ────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == BTN_VOCAB)
def on_vocab_request(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not _check_channel_or_block(uid, message.chat.id):
        return
    db.ensure_user(uid)

    # Agar vocab session bo'lsa, o'shandan foydalan
    ctx = db.session_context(uid)
    vocab_ctx = ctx.get("vocab") or {}

    if vocab_ctx and vocab_ctx.get("topic"):
        topic = vocab_ctx["topic"]
        keywords = vocab_ctx.get("keywords", [])
        collocations = vocab_ctx.get("collocations", [])

        # Narx tekshiruvi
        if not db.check_coins(uid, config.VOCAB_COST):
            bot.send_message(
                message.chat.id,
                f"❌ Yetarli tanga yo'q.\n\n"
                f"💰 Vocabulary narxi: {config.VOCAB_COST} tanga\n"
                f"📊 Balans: {db.get_coins(uid):.1f} tanga",
                reply_markup=main_menu_markup(uid),
            )
            return

        # To'lov
        ok, balance = db.deduct_coins(uid, config.VOCAB_COST, "vocabulary")
        if not ok:
            bot.send_message(
                message.chat.id,
                f"❌ Yetarli tanga yo'q. Kerak: {config.VOCAB_COST} tanga, balans: {balance:.1f}",
                reply_markup=main_menu_markup(uid),
            )
            return

        # Tahlil
        sys_prompt = prompts.vocabulary_detailed_prompt(topic, keywords, collocations)
        raw = ask_text_safe(sys_prompt, timeout=90)
        feedback = raw.rsplit("{", 1)[0].strip() if "{" in raw else raw

        bot.send_message(message.chat.id, feedback, reply_markup=main_menu_markup(uid))
        return

    # Vocabulary mavzu so'rash
    db.set_session(uid, "await_vocab_topic", {})
    bot.send_message(
        message.chat.id,
        f"📚 *Vocabulary Booster*\n\n"
        f"Qaysi mavzuda so'zlar o'rganmoqchisiz?\n\n"
        f"Misol: education, environment, technology, health, travel...\n\n"
        f"💰 Narx: {config.VOCAB_COST} tanga",
        parse_mode="Markdown",
    )


@bot.message_handler(
    func=lambda m: m.content_type == "text"
    and _sess_state(m, "await_vocab_topic")
    and m.text not in _ALL_MENU_BUTTONS
)
def on_vocab_topic_submit(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    topic = message.text.strip()
    if not topic or topic == BTN_BACK:
        db.clear_session(uid)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_markup(uid))
        return

    # Narx tekshiruvi
    if not db.check_coins(uid, config.VOCAB_COST):
        bot.send_message(
            message.chat.id,
            f"❌ Yetarli tanga yo'q.\n\n"
            f"💰 Vocabulary narxi: {config.VOCAB_COST} tanga\n"
            f"📊 Balans: {db.get_coins(uid):.1f} tanga\n\n"
            f"Boshqa mavzu kiriting yoki bekor qiling.",
        )
        return

    # To'lov
    ok, balance = db.deduct_coins(uid, config.VOCAB_COST, "vocabulary")
    if not ok:
        bot.send_message(
            message.chat.id,
            f"❌ Yetarli tanga yo'q. Kerak: {config.VOCAB_COST} tanga, balans: {balance:.1f}",
            reply_markup=main_menu_markup(uid),
        )
        db.clear_session(uid)
        return

    # AI dan vocabulary so'rash
    sys_prompt = prompts.vocabulary_detailed_prompt(topic, [], [])
    bot.send_chat_action(message.chat.id, "typing")
    raw = ask_text_safe(sys_prompt, timeout=90)
    feedback = raw.rsplit("{", 1)[0].strip() if "{" in raw else raw

    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        feedback,
        reply_markup=main_menu_markup(uid),
    )


# ── O'qituvchi: Guruh Hisoboti ─────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == BTN_GROUP_REPORT)
def on_group_report(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    row = db.get_user_row(uid)
    role = row["role"] if row else "STUDENT"

    if role != "TEACHER":
        bot.send_message(
            message.chat.id,
            "❌ Bu funksiya faqat o'qituvchilar uchun.",
            reply_markup=main_menu_markup(uid),
        )
        return

    # O'qituvchining o'quvchilarini olish
    students = db.get_teacher_students_with_submissions(uid)

    if not students:
        bot.send_message(
            message.chat.id,
            "📊 Hali o'quvchilar yo'q yoki ular writing yuborishmagan.",
            reply_markup=main_menu_markup(uid),
        )
        return

    # Ma'lumotlarni formatlash
    students_data = []
    for s in students:
        students_data.append({
            "user_id": s["user_id"],
            "mode": s["mode"],
            "last_band": s["overall_band"],
            "cefr": s["cefr_level"],
            "last_activity": s["created_at"],
            "task_type": s["task_type"],
        })

    # Period tanlash
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add("📅 Bugun", "📅 Haftalik", "📅 Oylik", BTN_BACK)
    db.set_session(uid, "group_report_period_pick", {})
    bot.send_message(
        message.chat.id,
        "👥 *Guruh Hisoboti*\n\n"
        f"O'quvchilar soni: {len(set(s['user_id'] for s in students))}\n"
        f"Jami writing'lar: {len(students)}\n\n"
        "Qaysi davr uchun hisobot kerak?",
        parse_mode="Markdown",
        reply_markup=markup,
    )


@bot.message_handler(
    func=lambda m: m.text in ("📅 Bugun", "📅 Haftalik", "📅 Oylik", BTN_BACK)
    and _sess_state(m, "group_report_period_pick")
)
def on_group_report_period(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if message.text == BTN_BACK:
        db.clear_session(uid)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_markup(uid))
        return

    period_map = {"📅 Bugun": "bugungi", "📅 Haftalik": "haftalik", "📅 Oylik": "oylik"}
    period = period_map.get(message.text, "haftalik")

    # O'quvchilar ma'lumotlarini yig'ish
    student_stats = db.get_student_stats_by_teacher(uid)

    if not student_stats:
        bot.send_message(
            message.chat.id,
            "📊 Hali yetarli ma'lumot yo'q.",
            reply_markup=main_menu_markup(uid),
        )
        db.clear_session(uid)
        return

    # Guruh tahlili prompti
    students_data = []
    for s in student_stats:
        students_data.append({
            "student_id": s["user_id"],
            "avg_band": round(s["avg_band"], 1) if s["avg_band"] else None,
            "writings": s["writing_count"],
        })

    sys_prompt = prompts.group_analysis_report_prompt(students_data, period)
    bot.send_chat_action(message.chat.id, "typing")
    raw = ask_text_safe(sys_prompt, timeout=120)
    feedback = raw.rsplit("{", 1)[0].strip() if "{" in raw else raw

    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        feedback,
        reply_markup=main_menu_markup(uid),
    )


def run_bot() -> None:
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    bot.infinity_polling(skip_pending=True, interval=1, timeout=60)
