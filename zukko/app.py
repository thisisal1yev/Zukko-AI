"""Telegram bot: handlers and polling."""
from __future__ import annotations

import json
import logging
import os
import random
import re
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
BTN_SPEAKING = "🎤 AI Speaking Tutor"
BTN_TEST = "📝 Daraja Aniqlash Testi"
BTN_STREAK = "🔥 Mening Streakim"
BTN_DIRECTION = "⬅️ Yo'nalish"
BTN_DASH = "📊 Progress Dashboard"
BTN_SAMPLES = "📚 Namunalar"
BTN_ERRORS = "📖 Xato lug'ati"
BTN_TEACHER = "👨‍🏫 O'qituvchi bog'lash"
BTN_CHALLENGE = "✨ Kunlik mini-challenge"
BTN_VOCAB = "📚 Vocabulary Booster"
BTN_PARAPHRASE = "🔁 Paraphrase o'yini"
BTN_UPGRADE = "⬆️ Upgrade so'z"
BTN_HELP = "😰 Writing yordam"

TASK_BTN = {"📊 Task 1": "task1", "📝 Task 2": "task2", "✉️ Letter": "letter"}

IELTS_START = "🇬🇧 IELTS Yo'nalishi"
CEFR_START = "🇺🇿 CEFR (Multi-level)"

_ALL_MENU_BUTTONS = frozenset(
    {
        BTN_TUTOR,
        BTN_SPEAKING,
        BTN_TEST,
        BTN_STREAK,
        BTN_DIRECTION,
        BTN_DASH,
        BTN_SAMPLES,
        BTN_ERRORS,
        BTN_TEACHER,
        BTN_CHALLENGE,
        BTN_VOCAB,
        BTN_PARAPHRASE,
        BTN_UPGRADE,
        BTN_HELP,
        IELTS_START,
        CEFR_START,
        "🔙 Orqaga",
        "🎙 Task 1 maslahat",
        "🎙 Task 2 maslahat",
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
    row = db.get_user_row(user_id)
    mode = row["mode"] if row else "IELTS"
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(
        MENU_WRITING(mode),
        BTN_TUTOR,
        BTN_SPEAKING,
        BTN_TEST,
        BTN_CHALLENGE,
        BTN_STREAK,
        BTN_DASH,
        BTN_SAMPLES,
        BTN_ERRORS,
        BTN_TEACHER,
        BTN_VOCAB,
        BTN_PARAPHRASE,
        BTN_UPGRADE,
        BTN_HELP,
        BTN_DIRECTION,
    )
    return m


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

    footer = f"\n\n🔥 Streak: {streak} | Rekord: {best}\n📚 Vocabulary: tugmalardan foydalaning."
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
    db.ensure_user(uid)
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(IELTS_START, CEFR_START)
    bot.send_message(
        message.chat.id,
        "Zukko AI Tutorga xush kelibsiz! Yo'nalishni tanlang:",
        reply_markup=m,
    )


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    db.clear_session(uid)
    bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_markup(uid))


def _direction_filter(message: types.Message) -> bool:
    if not message.text:
        return False
    t = message.text
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
    bot.send_message(
        message.chat.id,
        f"✅ {mode} rejasi faollashdi!",
        reply_markup=main_menu_markup(uid),
    )


def _starts_writing(text: str) -> bool:
    return text.startswith("✍️") and "Writing" in text


@bot.message_handler(func=lambda m: bool(m.text and _starts_writing(m.text)))
def on_writing_menu(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
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
    row = db.get_user_row(uid)
    mode = row["mode"] if row else "IELTS"
    sess = db.get_session(uid)
    state = sess["state"] if sess else None
    task_type = row["preferred_task"] if row else "task2"
    if state == "waiting_writing" and sess:
        ctx = db.session_context(uid)
        task_type = ctx.get("task_type") or task_type

    path = f"essay_{uid}_{message.message_id}.jpg"
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
        with open(path, "wb") as f:
            f.write(data)
        process_writing(message.chat.id, uid, mode, task_type, "image", None, path)
    except Exception as e:
        logger.exception("photo fail: %s", e)
        bot.send_message(message.chat.id, "⚠️ Xatolik yuz berdi.")
    finally:
        if os.path.exists(path):
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
    bot.send_message(message.chat.id, "Savolingizni yozing — ingliz tili o'qituvchisi sifatida javob beraman.")


@bot.message_handler(func=lambda m: m.text == BTN_SPEAKING)
def on_speaking_entry(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🎙 Task 1 maslahat", "🎙 Task 2 maslahat", "🔙 Orqaga")
    bot.send_message(message.chat.id, "Speaking: qaysi task bo'yicha?", reply_markup=kb)
    db.set_session(uid, "speaking_pick", {})


@bot.message_handler(
    func=lambda m: m.text in ("🎙 Task 1 maslahat", "🎙 Task 2 maslahat", "🔙 Orqaga")
    and _sess_state(m, "speaking_pick")
)
def on_speaking_pick(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    st = message.text
    if st == "🔙 Orqaga":
        db.clear_session(uid)
        bot.send_message(message.chat.id, "Menyu:", reply_markup=main_menu_markup(uid))
        return
    if st is None:
        return
    tt = "task1" if "Task 1" in st else "task2"
    row = db.get_user_row(uid)
    mode = row["mode"] if row else "IELTS"
    db.set_session(uid, "speaking_coach", {"task_type": tt, "mode": mode})
    bot.send_message(
        message.chat.id,
        "Speaking haqida savolingizni yozing (matn).",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(
    func=lambda m: m.content_type == "text"
    and _sess_state(m, "speaking_coach")
    and (m.text not in _ALL_MENU_BUTTONS)
    and (not _starts_writing(m.text or ""))
)
def on_speaking_chat(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    qtext = message.text or ""
    ctx = db.session_context(uid)
    tt = ctx.get("task_type", "task2")
    mode = ctx.get("mode", "IELTS")
    sys_p = prompts.speaking_tutor_system(mode, tt)
    res = ask_text_safe(f"{sys_p}\n\nSavol: {qtext}", timeout=90)
    bot.reply_to(message, res)


@bot.message_handler(func=lambda m: m.text == BTN_TEST)
def on_level_test(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    bank = _load_json(GRAMMAR_BANK_PATH).get("questions") or []
    if len(bank) < 5:
        row = db.get_user_row(uid)
        mode = row["mode"] if row else "IELTS"
        sample = '{"questions":[{"q":"...","options":["a","b","c","d"],"correct":1}]}'
        raw = ask_text_safe(prompts.grammar_test_generation(mode, sample), timeout=90)
        blob = extract_json_blob(raw) or {}
        bank = blob.get("questions") or []
    if not bank:
        bot.send_message(message.chat.id, "Test banki hozircha bo'sh.")
        return
    rng = random.Random(int(__import__("datetime").date.today().strftime("%Y%m%d")) + uid)
    picks = rng.sample(bank, min(5, len(bank)))
    db.set_session(uid, "grammar_quiz", {"questions": picks, "idx": 0, "correct": 0})
    _send_grammar_question(message.chat.id, picks[0], 0, len(picks))


def _send_grammar_question(chat_id: int, q: dict, idx: int, total: int) -> None:
    opts = q.get("options") or []
    lines = [f"Savol {idx+1}/{total}: {q.get('q','')}\n"]
    for i, o in enumerate(opts):
        lines.append(f"{i}. {o}")
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    for i in range(len(opts)):
        kb.add(str(i))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)


@bot.message_handler(
    func=lambda m: m.text is not None
    and re.fullmatch(r"\d+", (m.text or "").strip() or "")
    and _sess_state(m, "grammar_quiz")
)
def on_grammar_answer(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    gt = message.text
    if gt is None:
        return
    ctx = db.session_context(uid)
    picks = ctx.get("questions") or []
    idx = int(ctx.get("idx") or 0)
    correct_n = int(ctx.get("correct") or 0)
    choice = int(gt.strip())
    q = picks[idx] if idx < len(picks) else None
    if not q:
        db.clear_session(uid)
        return
    ok = q.get("correct")
    if choice == ok:
        correct_n += 1
    idx += 1
    if idx >= len(picks):
        db.save_grammar_result(uid, correct_n, len(picks), {"detail": "daily_grammar"})
        db.record_daily_activity(uid, met_goal=True)
        db.clear_session(uid)
        bot.send_message(
            message.chat.id,
            f"Test yakunlandi: {correct_n}/{len(picks)}.\nZo'r! Kunlik maqsad uchun streak yangilandi.",
            reply_markup=main_menu_markup(uid),
        )
        return
    db.set_session(uid, "grammar_quiz", {"questions": picks, "idx": idx, "correct": correct_n})
    _send_grammar_question(message.chat.id, picks[idx], idx, len(picks))


@bot.message_handler(func=lambda m: m.text == BTN_STREAK)
def on_streak(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    row = db.get_user_row(uid)
    sc = row["streak_current"] if row else 0
    sb = row["streak_best"] if row else 0
    dg = row["daily_goal_met_date"] if row else None
    from datetime import date

    today = date.today().isoformat()
    goal = "✅ bajarilgan" if dg == today else "⬜ hali yo'q"
    bot.send_message(
        message.chat.id,
        f"🔥 Ketma-ket kunlar: {sc}\n🏆 Rekord: {sb}\n🎯 Bugungi maqsad: {goal}",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(func=lambda m: m.text == BTN_DASH)
def on_dashboard(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    weak = db.get_weak_areas_summary(uid)
    row = db.get_user_row(uid)
    from datetime import date

    today = date.today().isoformat()
    dg = row["daily_goal_met_date"] if row else None
    goal = "bajarilgan" if dg == today else "kutilmoqda"
    sc = row["streak_current"] if row else 0
    last = db.get_last_scores(uid)
    band = last["overall_band"] if last else "-"
    cefr = last["cefr_level"] if last else "-"
    bot.send_message(
        message.chat.id,
        f"📊 Dashboard\nStreak: {sc}\nBugungi maqsad: {goal}\nSo'nggi band≈{band} CEFR={cefr}\n\n{weak}",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(func=lambda m: m.text == BTN_SAMPLES)
def on_samples(message: types.Message) -> None:
    data = _load_json(SAMPLES_PATH)
    uid = _user_id(message)
    if uid is None:
        return
    row = db.get_user_row(uid)
    task = row["preferred_task"] if row else "task2"
    sec = data.get(task) or data.get("task2") or {}
    if not sec:
        bot.send_message(message.chat.id, "Namunalar hozircha yo'q.")
        return
    for band in ("6", "7", "8", "9"):
        txt = sec.get(band)
        if txt:
            bot.send_message(message.chat.id, f"Band {band} namunasi:\n\n{txt}")
    bot.send_message(message.chat.id, "Tugadi.", reply_markup=main_menu_markup(uid))


@bot.message_handler(func=lambda m: m.text == BTN_ERRORS)
def on_errors(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    with db.get_conn() as conn:
        cur = conn.execute(
            """SELECT task_type, error_category, count, example_snippet FROM errors_log
               WHERE user_id = ? ORDER BY count DESC LIMIT 15""",
            (uid,),
        )
        rows = cur.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "Xatolar lug'ati hozircha bo'sh.", reply_markup=main_menu_markup(uid))
        return
    lines = ["📖 Xato lug'ati (top):"]
    for r in rows:
        lines.append(f"• [{r['task_type']}] {r['error_category']} ×{r['count']}")
    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=main_menu_markup(uid))


@bot.message_handler(func=lambda m: m.text == BTN_TEACHER)
def on_teacher_link(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    db.set_session(uid, "await_teacher_id", {})
    bot.send_message(
        message.chat.id,
        "O'qituvchining Telegram `user_id` (raqam) yuboring. O'qituvchi @userinfobot orqali olishi mumkin.",
        parse_mode="Markdown",
    )


@bot.message_handler(func=lambda m: m.content_type == "text" and _sess_state(m, "await_teacher_id"))
def on_teacher_id(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    if not message.text or not message.text.strip().lstrip("-").isdigit():
        bot.send_message(message.chat.id, "Faqat raqamli ID yuboring.")
        return
    tid = int(message.text.strip())
    db.set_teacher_id(uid, tid)
    db.clear_session(uid)
    bot.send_message(
        message.chat.id,
        f"✅ O'qituvchi ID saqlandi: `{tid}`. Yangi yozuvlar shu chatga xabar qilinadi.",
        reply_markup=main_menu_markup(uid),
        parse_mode="Markdown",
    )


@bot.message_handler(func=lambda m: m.text == BTN_CHALLENGE)
def on_daily_challenge(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    bank = _load_json(GRAMMAR_BANK_PATH).get("questions") or []
    if not bank:
        bot.send_message(message.chat.id, "Challenge uchun savollar yo'q.")
        return
    rng = random.Random(int(__import__("datetime").date.today().strftime("%Y%m%d")))
    q = rng.choice(bank)
    db.set_session(uid, "mini_challenge", {"q": q})
    opts = q.get("options") or []
    lines = ["✨ Kunlik mini-challenge\n", q.get("q", ""), ""]
    for i, o in enumerate(opts):
        lines.append(f"{i}. {o}")
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    for i in range(len(opts)):
        kb.add(str(i))
    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=kb)


@bot.message_handler(
    func=lambda m: m.text is not None
    and re.fullmatch(r"\d+", (m.text or "").strip() or "")
    and _sess_state(m, "mini_challenge")
)
def on_mini_answer(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    mt = message.text
    if mt is None:
        return
    ctx = db.session_context(uid)
    q = ctx.get("q") or {}
    choice = int(mt.strip())
    ok = q.get("correct")
    if choice == ok:
        db.record_daily_activity(uid, met_goal=True)
        msg = "✅ To'g'ri! Streak / maqsad yangilandi."
    else:
        msg = f"❌ Noto'g'ri. To'g'ri javob: {ok}"
    db.clear_session(uid)
    bot.send_message(message.chat.id, msg, reply_markup=main_menu_markup(uid))


@bot.message_handler(func=lambda m: m.text == BTN_VOCAB)
def on_vocab_booster(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    ctx = db.session_context(uid)
    vocab = ctx.get("vocab") or {}
    topic = vocab.get("topic") or "practice"
    kws = vocab.get("keywords") or []
    cols = vocab.get("collocations") or []
    if not kws:
        bot.send_message(
            message.chat.id,
            "Avval Writing tahlili qiling — so'zlar shu yerdan olinadi.",
            reply_markup=main_menu_markup(uid),
        )
        return
    lines = [f"Mavzu: {topic}\n", "Kalit so'zlar:", ", ".join(kws[:15])]
    if cols:
        lines.append("\nKollokatsiyalar:")
        lines.append(", ".join(cols[:10]))
    raw = ask_text_safe(prompts.vocab_pack_prompt(topic, kws, cols), timeout=90)
    data = extract_json_blob(raw)
    qs_raw = (data or {}).get("questions") if data else None
    if not isinstance(qs_raw, list) or not qs_raw:
        bot.send_message(message.chat.id, "\n".join(lines), reply_markup=main_menu_markup(uid))
        return
    qs: list = qs_raw
    prev_ctx = dict(db.session_context(uid))
    db.set_session(
        uid,
        "vocab_quiz",
        {"questions": qs, "idx": 0, "correct": 0, "restore": prev_ctx},
    )
    _send_vocab_q(message.chat.id, qs[0], 0, len(qs))


def _send_vocab_q(chat_id: int, q: dict, idx: int, total: int) -> None:
    opts = q.get("options") or []
    lines = [f"Quiz {idx+1}/{total}: {q.get('q','')}\n"]
    for i, o in enumerate(opts):
        lines.append(f"{i}. {o}")
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    for i in range(len(opts)):
        kb.add(str(i))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)


@bot.message_handler(
    func=lambda m: m.text is not None
    and re.fullmatch(r"\d+", (m.text or "").strip() or "")
    and _sess_state(m, "vocab_quiz")
)
def on_vocab_quiz_answer(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    text = message.text
    if text is None:
        return
    ctx = db.session_context(uid)
    qs = ctx.get("questions") or []
    idx = int(ctx.get("idx") or 0)
    corr = int(ctx.get("correct") or 0)
    restore = ctx.get("restore") or {}
    choice = int(text.strip())
    q = qs[idx] if idx < len(qs) else None
    if not q:
        db.clear_session(uid)
        return
    if choice == int(q.get("correct", -1)):
        corr += 1
    expl = q.get("explain_uz") or ""
    idx += 1
    if expl:
        bot.send_message(message.chat.id, expl)
    if idx >= len(qs):
        db.record_daily_activity(uid, met_goal=True)
        restored = restore if isinstance(restore, dict) else {}
        db.set_session(uid, "idle", restored)
        bot.send_message(
            message.chat.id,
            f"Vocab quiz tugadi: {corr}/{len(qs)}.",
            reply_markup=main_menu_markup(uid),
        )
        return
    db.set_session(
        uid,
        "vocab_quiz",
        {"questions": qs, "idx": idx, "correct": corr, "restore": restore},
    )
    _send_vocab_q(message.chat.id, qs[idx], idx, len(qs))


@bot.message_handler(func=lambda m: m.text == BTN_PARAPHRASE)
def on_paraphrase_start(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    ctx = db.session_context(uid)
    kws = (ctx.get("vocab") or {}).get("keywords") or []
    sent = "Technology has changed the way children learn in schools."
    if kws:
        sent = f"Students should practice using words like: {', '.join(kws[:4])}."
    db.set_session(uid, "paraphrase_wait", {"original": sent})
    bot.send_message(
        message.chat.id,
        f"Quyidagi gapni o'zingizcha qayta yozing (Inglizcha):\n\n{sent}",
        reply_markup=main_menu_markup(uid),
    )


@bot.message_handler(
    func=lambda m: m.content_type == "text"
    and _sess_state(m, "paraphrase_wait")
    and bool(m.text)
    and (m.text not in _ALL_MENU_BUTTONS)
    and not _starts_writing(m.text or "")
    and not re.fullmatch(r"\d+", (m.text or "").strip())
)
def on_paraphrase_reply(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    reply = message.text
    if reply is None:
        return
    ctx = db.session_context(uid)
    orig = ctx.get("original", "")
    res = ask_text_safe(prompts.paraphrase_judge_prompt(orig, reply), timeout=60)
    db.clear_session(uid)
    db.record_daily_activity(uid, met_goal=True)
    bot.reply_to(message, res)
    bot.send_message(message.chat.id, "Menyu:", reply_markup=main_menu_markup(uid))


@bot.message_handler(func=lambda m: m.text == BTN_UPGRADE)
def on_upgrade_word(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    ctx = db.session_context(uid)
    kws = (ctx.get("vocab") or {}).get("keywords") or []
    word = (kws[0] if kws else "important")
    sent = f"The graph shows an important trend over time."
    res = ask_text_safe(prompts.upgrade_word_prompt(word, sent), timeout=60)
    db.record_daily_activity(uid, met_goal=True)
    bot.send_message(message.chat.id, res, reply_markup=main_menu_markup(uid))


@bot.message_handler(func=lambda m: m.text == BTN_HELP)
def on_writing_help(message: types.Message) -> None:
    _send_demo_cta(message.chat.id)


def _fallback_allowed(message: types.Message) -> bool:
    if message.content_type != "text" or not message.text:
        return False
    t = message.text
    blocked = {
        BTN_TUTOR,
        BTN_SPEAKING,
        BTN_TEST,
        BTN_STREAK,
        BTN_DIRECTION,
        BTN_DASH,
        BTN_SAMPLES,
        BTN_ERRORS,
        BTN_TEACHER,
        BTN_CHALLENGE,
        BTN_VOCAB,
        BTN_PARAPHRASE,
        BTN_UPGRADE,
        BTN_HELP,
        IELTS_START,
        CEFR_START,
        "🔙 Orqaga",
        "🎙 Task 1 maslahat",
        "🎙 Task 2 maslahat",
    }
    if t in blocked or t in TASK_BTN:
        return False
    if _starts_writing(t):
        return False
    if t in ("📊 Task 1", "📝 Task 2", "✉️ Letter"):
        return False
    uid = _user_id(message)
    if uid is None:
        return False
    sess = db.get_session(uid)
    if sess and sess["state"] in (
        "grammar_quiz",
        "vocab_quiz",
        "mini_challenge",
        "await_teacher_id",
        "paraphrase_wait",
        "speaking_coach",
        "speaking_pick",
        "waiting_writing",
        "pick_task",
    ):
        return False
    return True


@bot.message_handler(func=_fallback_allowed)
def on_fallback_text(message: types.Message) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    q = message.text
    if not q:
        return
    row = db.get_user_row(uid)
    mode = row["mode"] if row else "IELTS"
    bot.send_chat_action(message.chat.id, "typing")
    res = ask_text_safe(f"Ingliz tili o'qituvchisi sifatida ({mode} kontekstida) javob ber: {q}")
    bot.reply_to(message, res)


def run_bot() -> None:
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    bot.infinity_polling(skip_pending=True, interval=1, timeout=60)
