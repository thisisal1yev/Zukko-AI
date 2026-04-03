"""SQLite persistence: users, submissions, errors, sessions, vocab."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Optional

DB_PATH = "zukkotutor.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


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
                demo_offered INTEGER DEFAULT 0
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
    for sql in alters:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass
    c.execute("UPDATE users SET streak_current = streak WHERE streak_current = 0 AND streak > 0")


def ensure_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )


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
