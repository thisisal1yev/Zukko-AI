"""SQLite persistence: users, submissions, errors, sessions, vocab."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Optional

DB_PATH = "zukkotutor.db"
_MAX_RETRIES = 3


@contextmanager
def get_conn(retry_count: int = 0):
    import time
    import logging
    logger = logging.getLogger(__name__)
    
    for attempt in range(_MAX_RETRIES):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=60)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()
            return  # muvaffaqiyatli bo'lsa, chiqish
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower() and attempt < _MAX_RETRIES - 1:
                wait_time = 0.5 * (attempt + 1)
                logger.warning("DB locked, retry %d/%d after %.1fs", attempt + 1, _MAX_RETRIES, wait_time)
                time.sleep(wait_time)
            else:
                raise


def init_db() -> None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                mode TEXT DEFAULT 'IELTS',
                preferred_task TEXT DEFAULT 'task2',
                streak INTEGER DEFAULT 0,
                streak_current INTEGER DEFAULT 0,
                streak_best INTEGER DEFAULT 0,
                last_active_date TEXT,
                daily_goal_met_date TEXT,
                teacher_id INTEGER,
                link_code TEXT,
                low_band_count INTEGER DEFAULT 0,
                demo_offered INTEGER DEFAULT 0,
                role TEXT DEFAULT 'STUDENT',
                coins REAL DEFAULT 0,
                tariff TEXT DEFAULT 'FREE',
                tariff_expires TEXT,
                combo_streak INTEGER DEFAULT 0,
                free_spins INTEGER DEFAULT 0,
                daily_writing_count INTEGER DEFAULT 0,
                daily_writing_date TEXT,
                daily_paraphrase_count INTEGER DEFAULT 0,
                daily_paraphrase_date TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                join_code TEXT NOT NULL UNIQUE,
                teacher_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS writing_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                task_type TEXT NOT NULL,
                input_type TEXT NOT NULL,
                transcript TEXT,
                model_user TEXT,
                scores_json TEXT,
                feedback_text TEXT,
                overall_band REAL,
                cefr_level TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS errors_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                error_category TEXT NOT NULL,
                example_snippet TEXT,
                count INTEGER DEFAULT 1,
                last_seen TEXT NOT NULL,
                UNIQUE(user_id, task_type, error_category)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS vocab_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                submission_id INTEGER,
                topic TEXT,
                words_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                context_json TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS grammar_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                detail_json TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                amount REAL NOT NULL,
                service_type TEXT NOT NULL,
                balance_after REAL NOT NULL,
                detail_json TEXT
            )"""
        )
        _migrate_users_columns(conn)


def _migrate_users_columns(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.execute("PRAGMA table_info(users)")
    cols = {row[1] for row in c.fetchall()}
    alters = []
    if "streak_current" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN streak_current INTEGER DEFAULT 0")
    if "streak_best" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN streak_best INTEGER DEFAULT 0")
    if "last_active_date" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN last_active_date TEXT")
    if "daily_goal_met_date" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN daily_goal_met_date TEXT")
    if "teacher_id" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN teacher_id INTEGER")
    if "link_code" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN link_code TEXT")
    if "low_band_count" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN low_band_count INTEGER DEFAULT 0")
    if "demo_offered" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN demo_offered INTEGER DEFAULT 0")
    if "preferred_task" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN preferred_task TEXT DEFAULT 'task2'")
    if "role" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'STUDENT'")
    if "coins" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN coins REAL DEFAULT 0")
    if "tariff" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN tariff TEXT DEFAULT 'FREE'")
    if "tariff_expires" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN tariff_expires TEXT")
    if "combo_streak" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN combo_streak INTEGER DEFAULT 0")
    if "free_spins" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN free_spins INTEGER DEFAULT 0")
    if "daily_writing_count" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN daily_writing_count INTEGER DEFAULT 0")
    if "daily_writing_date" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN daily_writing_date TEXT")
    if "daily_paraphrase_count" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN daily_paraphrase_count INTEGER DEFAULT 0")
    if "daily_paraphrase_date" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN daily_paraphrase_date TEXT")
    if "first_name" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN first_name TEXT")
    if "last_name" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN last_name TEXT")
    if "phone" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN phone TEXT")
    if "telegram_username" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN telegram_username TEXT")
    if "is_registered" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN is_registered INTEGER DEFAULT 0")
    if "channels_subscribed" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN channels_subscribed INTEGER DEFAULT 0")
    if "group_id" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN group_id INTEGER")
    for sql in alters:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass
    c.execute("UPDATE users SET streak_current = streak WHERE streak_current = 0 AND streak > 0")


def ensure_user(user_id: int) -> None:
    import time
    import logging
    logger = logging.getLogger(__name__)
    
    for attempt in range(_MAX_RETRIES):
        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
                    (user_id,),
                )
            return
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower() and attempt < _MAX_RETRIES - 1:
                wait_time = 0.5 * (attempt + 1)
                logger.warning("ensure_user locked, retry %d/%d after %.1fs", attempt + 1, _MAX_RETRIES, wait_time)
                time.sleep(wait_time)
            else:
                raise


def ensure_user_with_bonus(user_id: int, bonus_amount: float = 0.0) -> bool:
    """
    Foydalanuvchini yaratadi va agar kerak bo'lsa bonus tanga qo'shadi.
    Bitta transaction da — locking muammosini kamaytiradi.
    """
    import time
    import logging
    logger = logging.getLogger(__name__)
    
    for attempt in range(_MAX_RETRIES):
        try:
            with get_conn() as conn:
                # Avval foydalanuvchini yaratish
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
                    (user_id,),
                )
                
                # Agar bonus kerak bo'lsa
                if bonus_amount > 0:
                    cur = conn.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
                    row = cur.fetchone()
                    current = float(row["coins"]) if row and row["coins"] is not None else 0
                    
                    if current == 0:  # Faqat birinchi marta
                        new_balance = current + bonus_amount
                        conn.execute("UPDATE users SET coins = ? WHERE user_id = ?", (new_balance, user_id))
                        created = datetime.utcnow().isoformat() + "Z"
                        conn.execute(
                            """INSERT INTO transactions (user_id, created_at, amount, service_type, balance_after, detail_json)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (user_id, created, bonus_amount, "initial_bonus", new_balance, json.dumps({"type": "credit"})),
                        )
                        return True  # Bonus berildi
                return False  # Bonus berilmadi (allaqachon bor)
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower() and attempt < _MAX_RETRIES - 1:
                wait_time = 0.5 * (attempt + 1)
                logger.warning("ensure_user_with_bonus locked, retry %d/%d after %.1fs", attempt + 1, _MAX_RETRIES, wait_time)
                time.sleep(wait_time)
            else:
                raise
    return False


def get_user_row(user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cur.fetchone()


def set_user_mode(user_id: int, mode: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET mode = ? WHERE user_id = ?", (mode, user_id))


def set_preferred_task(user_id: int, task: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET preferred_task = ? WHERE user_id = ?",
            (task, user_id),
        )


def set_teacher_id(user_id: int, teacher_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET teacher_id = ? WHERE user_id = ?",
            (teacher_id, user_id),
        )


def record_daily_activity(user_id: int, met_goal: bool = True) -> tuple[int, int]:
    """Update calendar streak and optionally daily goal. Returns (streak_current, streak_best)."""
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT last_active_date, streak_current, streak_best FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        last = row["last_active_date"] if row else None
        sc = row["streak_current"] if row and row["streak_current"] is not None else 0
        sb = row["streak_best"] if row and row["streak_best"] is not None else 0

        if last == today:
            new_sc = sc
        elif last == yesterday:
            new_sc = sc + 1
        else:
            new_sc = 1
        new_sb = max(sb, new_sc)
        if met_goal:
            conn.execute(
                """UPDATE users SET last_active_date = ?, streak_current = ?, streak_best = ?,
                   daily_goal_met_date = ? WHERE user_id = ?""",
                (today, new_sc, new_sb, today, user_id),
            )
        else:
            conn.execute(
                """UPDATE users SET last_active_date = ?, streak_current = ?, streak_best = ?
                   WHERE user_id = ?""",
                (today, new_sc, new_sb, user_id),
            )
        return new_sc, new_sb


def insert_submission(
    user_id: int,
    mode: str,
    task_type: str,
    input_type: str,
    transcript: str,
    model: str,
    scores_json: Optional[dict],
    feedback_text: str,
    overall_band: Optional[float],
    cefr_level: Optional[str],
) -> int:
    created = datetime.utcnow().isoformat() + "Z"
    sj = json.dumps(scores_json, ensure_ascii=False) if scores_json else None
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO writing_submissions
            (user_id, created_at, mode, task_type, input_type, transcript, model_user,
             scores_json, feedback_text, overall_band, cefr_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                created,
                mode,
                task_type,
                input_type,
                transcript,
                model,
                sj,
                feedback_text,
                overall_band,
                cefr_level,
            ),
        )
        return int(cur.lastrowid)


def upsert_errors(user_id: int, task_type: str, errors: list[dict]) -> None:
    if not errors:
        return
    now = datetime.utcnow().isoformat() + "Z"
    with get_conn() as conn:
        for e in errors:
            cat = str(e.get("category") or "general")[:120]
            snip = str(e.get("snippet") or "")[:500]
            conn.execute(
                """INSERT INTO errors_log (user_id, task_type, error_category, example_snippet, count, last_seen)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(user_id, task_type, error_category) DO UPDATE SET
                  count = count + 1,
                  example_snippet = excluded.example_snippet,
                  last_seen = excluded.last_seen""",
                (user_id, task_type, cat, snip, now),
            )


def get_error_summary_for_prompt(user_id: int, task_type: str, limit: int = 8) -> str:
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT error_category, SUM(count) as c FROM errors_log
               WHERE user_id = ? AND task_type = ? GROUP BY error_category ORDER BY c DESC LIMIT ?""",
            (user_id, task_type, limit),
        )
        rows = cur.fetchall()
    if not rows:
        return ""
    parts = [f"- {r['error_category']}: {r['c']} marta" for r in rows]
    return "O'quvchining tez-tez qaytaladigan xatolari (shu task bo'yicha):\n" + "\n".join(parts)


def get_weak_areas_summary(user_id: int) -> str:
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT error_category, SUM(count) as c FROM errors_log
               WHERE user_id = ? GROUP BY error_category ORDER BY c DESC LIMIT 5""",
            (user_id,),
        )
        rows = cur.fetchall()
        cur2 = conn.execute(
            """SELECT mode, task_type, overall_band, cefr_level, created_at
               FROM writing_submissions WHERE user_id = ? ORDER BY id DESC LIMIT 3""",
            (user_id,),
        )
        recent = cur2.fetchall()
    lines = []
    if rows:
        lines.append("Top xato kalitlari:")
        for r in rows:
            lines.append(f"  • {r['error_category']}: {r['c']}")
    else:
        lines.append("Xatolar log'i hali bo'sh.")
    if recent:
        lines.append("\nSo'nggi yozuvlar:")
        for r in recent:
            lines.append(
                f"  • {r['task_type']} ({r['mode']}) band≈{r['overall_band']} CEFR={r['cefr_level'] or '-'}"
            )
    return "\n".join(lines)


def get_last_scores(user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT overall_band, cefr_level, task_type FROM writing_submissions
               WHERE user_id = ? ORDER BY id DESC LIMIT 1""",
            (user_id,),
        )
        return cur.fetchone()


def save_vocab_session(user_id: int, submission_id: Optional[int], topic: str, words: dict) -> int:
    created = datetime.utcnow().isoformat() + "Z"
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO vocab_sessions (user_id, submission_id, topic, words_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, submission_id, topic, json.dumps(words, ensure_ascii=False), created),
        )
        return int(cur.lastrowid)


def get_session(user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM user_sessions WHERE user_id = ?", (user_id,))
        return cur.fetchone()


def set_session(user_id: int, state: str, context: Optional[dict] = None) -> None:
    ctx = json.dumps(context, ensure_ascii=False) if context else None
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO user_sessions (user_id, state, context_json) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET state = excluded.state, context_json = excluded.context_json""",
            (user_id, state, ctx),
        )


def clear_session(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))


def session_context(user_id: int) -> dict:
    row = get_session(user_id)
    if not row or not row["context_json"]:
        return {}
    try:
        return json.loads(row["context_json"])
    except json.JSONDecodeError:
        return {}


def update_session_context(user_id: int, **kwargs: Any) -> None:
    ctx = session_context(user_id)
    ctx.update(kwargs)
    row = get_session(user_id)
    state = row["state"] if row else "idle"
    set_session(user_id, state, ctx)


def mark_demo_offered(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET demo_offered = 1 WHERE user_id = ?", (user_id,))


def update_low_band_streak(
    user_id: int, low_band_threshold: float, streak_for_demo: int, overall_band: Optional[float]
) -> bool:
    """After a writing score: bump or reset low_band counter. Returns True if demo CTA should show."""
    row = get_user_row(user_id)
    if not row or row["demo_offered"]:
        return False
    with get_conn() as conn:
        if overall_band is not None and overall_band <= low_band_threshold:
            conn.execute(
                "UPDATE users SET low_band_count = low_band_count + 1 WHERE user_id = ?",
                (user_id,),
            )
        elif overall_band is not None and overall_band > low_band_threshold:
            conn.execute("UPDATE users SET low_band_count = 0 WHERE user_id = ?", (user_id,))
        cur = conn.execute("SELECT low_band_count FROM users WHERE user_id = ?", (user_id,))
        r = cur.fetchone()
        cnt = int(r["low_band_count"]) if r else 0
    return cnt >= streak_for_demo


def save_grammar_result(user_id: int, score: int, total: int, detail: dict) -> None:
    created = datetime.utcnow().isoformat() + "Z"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO grammar_results (user_id, created_at, score, total, detail_json)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, created, score, total, json.dumps(detail, ensure_ascii=False)),
        )


# =============================================================================
# COINS / TANGA TIZIMI
# =============================================================================

def set_user_role(user_id: int, role: str) -> None:
    """TEACHER yoki STUDENT rol o'rnatish."""
    with get_conn() as conn:
        conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (role.upper(), user_id))


def add_coins(user_id: int, amount: float, reason: str = "topup") -> float:
    """Tanga qo'shish. Yangi balansni qaytaradi."""
    with get_conn() as conn:
        cur = conn.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        current = float(row["coins"]) if row and row["coins"] is not None else 0
        new_balance = current + amount
        conn.execute("UPDATE users SET coins = ? WHERE user_id = ?", (new_balance, user_id))
        insert_transaction(user_id, amount, reason, new_balance, {"type": "credit"})
        return new_balance


def get_coins(user_id: int) -> float:
    """Joriy tanga balansini qaytaradi."""
    row = get_user_row(user_id)
    if not row or row["coins"] is None:
        return 0
    return float(row["coins"])


def check_coins(user_id: int, cost: float) -> bool:
    """Yetarli tanga borligini tekshiradi."""
    return get_coins(user_id) >= cost


def deduct_coins(user_id: int, cost: float, service_type: str) -> tuple[bool, float]:
    """
    Tanga yechish. (muvaffaqiyat, qolgan_balans) tuple qaytaradi.
    Agar yetarli bo'lmasa, (False, current_balance).
    """
    current = get_coins(user_id)
    if current < cost:
        return False, current
    with get_conn() as conn:
        new_balance = current - cost
        conn.execute("UPDATE users SET coins = ? WHERE user_id = ?", (new_balance, user_id))
        insert_transaction(user_id, -cost, service_type, new_balance, {"type": "debit"})
        return True, new_balance


def insert_transaction(user_id: int, amount: float, service_type: str, balance_after: float, detail: dict) -> None:
    """Tranzaksiya yozuvini qo'shadi."""
    created = datetime.utcnow().isoformat() + "Z"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO transactions (user_id, created_at, amount, service_type, balance_after, detail_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, created, amount, service_type, balance_after, json.dumps(detail, ensure_ascii=False)),
        )


def get_transactions(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    """Foydalanuvchining oxirgi tranzaksiyalarini qaytaradi."""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        )
        return cur.fetchall()


# =============================================================================
# TARIF LIMITLAR
# =============================================================================

def reset_daily_limits_if_needed(user_id: int) -> None:
    """Agar yangi kun bo'lsa, kunlik limitlarni reset qiladi."""
    today = date.today().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT daily_writing_date, daily_paraphrase_date FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return
        w_date = row["daily_writing_date"]
        p_date = row["daily_paraphrase_date"]
        if w_date != today:
            conn.execute(
                "UPDATE users SET daily_writing_count = 0, daily_writing_date = ? WHERE user_id = ?",
                (today, user_id),
            )
        if p_date != today:
            conn.execute(
                "UPDATE users SET daily_paraphrase_count = 0, daily_paraphrase_date = ? WHERE user_id = ?",
                (today, user_id),
            )


def get_daily_writing_count(user_id: int) -> int:
    """Bugungi writing tahlillar soni."""
    reset_daily_limits_if_needed(user_id)
    row = get_user_row(user_id)
    if not row or row["daily_writing_count"] is None:
        return 0
    return int(row["daily_writing_count"])


def increment_daily_writing(user_id: int) -> int:
    """Writing hisoblagichni oshiradi va yangi qiymatni qaytaradi."""
    reset_daily_limits_if_needed(user_id)
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET daily_writing_count = daily_writing_count + 1 WHERE user_id = ?",
            (user_id,),
        )
        cur = conn.execute("SELECT daily_writing_count FROM users WHERE user_id = ?", (user_id,))
        r = cur.fetchone()
        return int(r["daily_writing_count"]) if r else 1


def get_daily_paraphrase_count(user_id: int) -> int:
    """Bugungi paraphrase o'yinlar soni."""
    reset_daily_limits_if_needed(user_id)
    row = get_user_row(user_id)
    if not row or row["daily_paraphrase_count"] is None:
        return 0
    return int(row["daily_paraphrase_count"])


def increment_daily_paraphrase(user_id: int) -> int:
    """Paraphrase hisoblagichni oshiradi va yangi qiymatni qaytaradi."""
    reset_daily_limits_if_needed(user_id)
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET daily_paraphrase_count = daily_paraphrase_count + 1 WHERE user_id = ?",
            (user_id,),
        )
        cur = conn.execute("SELECT daily_paraphrase_count FROM users WHERE user_id = ?", (user_id,))
        r = cur.fetchone()
        return int(r["daily_paraphrase_count"]) if r else 1


def update_combo_streak(user_id: int, increment: bool = True) -> tuple[int, int]:
    """
    Combo streak ni yangilaydi.
    (yangi_streak, qozonilgan_free_spin) qaytaradi.
    3 combo -> 1 free spin, 5 combo -> 2 free spin.
    """
    row = get_user_row(user_id)
    current_streak = int(row["combo_streak"]) if row and row["combo_streak"] is not None else 0
    current_free = int(row["free_spins"]) if row and row["free_spins"] is not None else 0

    if increment:
        current_streak += 1
    else:
        current_streak = 0

    earned_spin = 0
    if current_streak == 3:
        earned_spin = 1
    elif current_streak == 5:
        earned_spin = 2

    if earned_spin > 0:
        current_free += earned_spin
        current_streak = 0  # reset after earning

    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET combo_streak = ?, free_spins = ? WHERE user_id = ?",
            (current_streak, current_free, user_id),
        )

    return current_streak, earned_spin


def get_paraphrase_reward(combo_streak: int) -> float:
    """
    Combo streak'ga qarab tanga mukofotini qaytaradi.
    0: 0 tanga
    1-3: 1.0 tanga
    4-10: 1.2 tanga
    10+: 1.5 tanga
    """
    if combo_streak <= 0:
        return 0.0
    elif combo_streak <= 3:
        return 1.0
    elif combo_streak <= 10:
        return 1.2
    else:
        return 1.5


def reset_combo_streak(user_id: int) -> None:
    """Combo streak'ni 0 ga tushiradi (streak buzilganda)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET combo_streak = 0 WHERE user_id = ?",
            (user_id,),
        )


def use_free_spin(user_id: int) -> bool:
    """Bitta tekin baraban ishlatadi. Muvaffaqiyatli bo'lsa True."""
    row = get_user_row(user_id)
    free = int(row["free_spins"]) if row and row["free_spins"] is not None else 0
    if free <= 0:
        return False
    with get_conn() as conn:
        conn.execute("UPDATE users SET free_spins = free_spins - 1 WHERE user_id = ?", (user_id,))
        return True


def set_tariff(user_id: int, tariff: str, expires: str | None = None) -> None:
    """Tarifni o'rnatadi."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET tariff = ?, tariff_expires = ? WHERE user_id = ?",
            (tariff.upper(), expires, user_id),
        )


def is_tariff_active(user_id: int) -> bool:
    """Tarif hali amal qilishini tekshiradi."""
    row = get_user_row(user_id)
    if not row:
        return False
    tariff = row["tariff"] or "FREE"
    expires = row["tariff_expires"]
    if tariff == "FREE" or not expires:
        return False
    try:
        exp_date = datetime.fromisoformat(expires)
        return exp_date > datetime.now()
    except (ValueError, TypeError):
        return False


# =============================================================================
# REGISTRATSIYA
# =============================================================================

def update_user_profile(user_id: int, first_name: str | None = None, last_name: str | None = None,
                        phone: str | None = None, telegram_username: str | None = None) -> None:
    """Foydalanuvchi profilini yangilaydi."""
    with get_conn() as conn:
        if first_name is not None:
            conn.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (first_name, user_id))
        if last_name is not None:
            conn.execute("UPDATE users SET last_name = ? WHERE user_id = ?", (last_name, user_id))
        if phone is not None:
            conn.execute("UPDATE users SET phone = ? WHERE user_id = ?", (phone, user_id))
        if telegram_username is not None:
            conn.execute("UPDATE users SET telegram_username = ? WHERE user_id = ?", (telegram_username, user_id))


def mark_registered(user_id: int) -> None:
    """Foydalanuvchini ro'yxatdan o'tgan deb belgilaydi."""
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_registered = 1 WHERE user_id = ?", (user_id,))


def is_registered(user_id: int) -> bool:
    """Foydalanuvchi ro'yxatdan o'tganligini tekshiradi."""
    row = get_user_row(user_id)
    if not row:
        return False
    return bool(row["is_registered"])


def mark_channels_subscribed(user_id: int) -> None:
    """Foydalanuvchi kanallarga obuna bo'lgan deb belgilaydi."""
    with get_conn() as conn:
        conn.execute("UPDATE users SET channels_subscribed = 1 WHERE user_id = ?", (user_id,))


def is_channels_subscribed(user_id: int) -> bool:
    """Foydalanuvchi kanallarga obuna bo'lganligini tekshiradi."""
    row = get_user_row(user_id)
    if not row:
        return False
    return bool(row["channels_subscribed"])


# =============================================================================
# GURUH (GROUPS) BOSHQARUVI
# =============================================================================

import random
import string

def generate_join_code(length: int = 8) -> str:
    """Tasodifiy qo'shilish kodi generatsiya qiladi."""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        # Unikal ekanligini tekshirish
        with get_conn() as conn:
            cur = conn.execute("SELECT id FROM groups WHERE join_code = ?", (code,))
            if not cur.fetchone():
                return code


def create_group(name: str, teacher_id: int) -> dict:
    """Yangi guruh yaratadi. (id, name, join_code) qaytaradi."""
    created = datetime.utcnow().isoformat() + "Z"
    code = generate_join_code()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO groups (name, join_code, teacher_id, created_at) VALUES (?, ?, ?, ?)",
            (name, code, teacher_id, created),
        )
        return {"id": int(cur.lastrowid), "name": name, "join_code": code}


def get_group_by_code(code: str) -> Optional[sqlite3.Row]:
    """Qo'shilish kodi orqali guruh topadi."""
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM groups WHERE join_code = ?", (code.upper(),))
        return cur.fetchone()


def get_group_by_id(group_id: int) -> Optional[sqlite3.Row]:
    """ID orqali guruh topadi."""
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,))
        return cur.fetchone()


def get_group_students(group_id: int) -> list[sqlite3.Row]:
    """Guruhdagi o'quvchilar ro'yxatini qaytaradi."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM users WHERE group_id = ? ORDER BY user_id",
            (group_id,),
        )
        return cur.fetchall()


def set_group_id(user_id: int, group_id: Optional[int]) -> None:
    """O'quvchini guruhga bog'laydi yoki ajratadi."""
    with get_conn() as conn:
        conn.execute("UPDATE users SET group_id = ? WHERE user_id = ?", (group_id, user_id))


def get_teacher_groups(teacher_id: int) -> list[sqlite3.Row]:
    """O'qituvchining barcha guruhlarini qaytaradi."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM groups WHERE teacher_id = ? ORDER BY created_at DESC",
            (teacher_id,),
        )
        return cur.fetchall()
