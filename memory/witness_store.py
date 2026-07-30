"""
Witness diary - JD's persistent memory of who and what it has seen.

memory/witness_recorder.py writes events here while the vision pipeline
runs; jd_robot_system/memory_context.py reads them back as a plain-text
block for the Gemini prompt. That keeps exactly one brain: the same
Gemini call that already handles conversation and action matching also
answers "who did you see today?". There is no separate answering path
that could disagree with it.

SQLite in WAL mode so the recorder keeps writing while main.py reads
from another process, without either one blocking. Both sides open a
short-lived connection per operation - at a few events per minute the
connect cost is nothing, and it means neither process can hold the
database hostage if it crashes.
"""

import os
import sqlite3
import time

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("JD_DIARY_DB", os.path.join(_BASE_DIR, "witness_diary.sqlite3"))

# Events older than this get pruned when the recorder starts, so the
# database stays tiny and diary queries stay instant forever.
KEEP_DAYS = float(os.environ.get("JD_DIARY_KEEP_DAYS", "14"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     REAL NOT NULL,
    kind   TEXT NOT NULL,
    person TEXT,
    detail TEXT,
    text   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_person ON events(person, ts);
"""


def _connect(db_path):
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    return conn


def record_event(kind, text, person=None, detail=None, ts=None, db_path=DB_PATH):
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO events (ts, kind, person, detail, text) VALUES (?, ?, ?, ?, ?)",
                (ts if ts is not None else time.time(), kind, person, detail, text),
            )
    finally:
        conn.close()


def prune_old_events(db_path=DB_PATH, keep_days=KEEP_DAYS):
    cutoff = time.time() - keep_days * 86400
    conn = _connect(db_path)
    try:
        with conn:
            removed = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,)).rowcount
        return removed
    finally:
        conn.close()


def recent_events(limit=10, db_path=DB_PATH):
    """Newest `limit` events, returned oldest-first so they read as a
    timeline. Rows are (ts, kind, person, detail, text)."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ts, kind, person, detail, text FROM events "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return list(reversed(rows))


def _people_seen_since(since_ts, db_path):
    """(person, first_ts, last_ts) per person sighted since since_ts.
    'system' and object events carry person=NULL, so they never leak in."""
    conn = _connect(db_path)
    try:
        return conn.execute(
            "SELECT person, MIN(ts), MAX(ts) FROM events "
            "WHERE person IS NOT NULL AND ts >= ? "
            "GROUP BY person ORDER BY MIN(ts)",
            (since_ts,),
        ).fetchall()
    finally:
        conn.close()


def _last_seen_per_person(db_path):
    conn = _connect(db_path)
    try:
        return conn.execute(
            "SELECT person, MAX(ts) FROM events WHERE person IS NOT NULL "
            "GROUP BY person ORDER BY MAX(ts) DESC",
        ).fetchall()
    finally:
        conn.close()


def _local_midnight(now):
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _fmt_time(ts, now):
    """Human time that stays short: today -> 14:31, this week ->
    Tue 14:31, older -> Jul 22 14:31. Gemini reasons about 'today' and
    'yesterday' far more reliably from these than from raw epochs."""
    if ts >= _local_midnight(now):
        return time.strftime("%H:%M", time.localtime(ts))
    if now - ts < 6 * 86400:
        return time.strftime("%a %H:%M", time.localtime(ts))
    return time.strftime("%b %d %H:%M", time.localtime(ts))


def _pool_label(person):
    return "unknown people" if person == "unknown" else person


def diary_context(now=None, max_events=10, max_chars=900, db_path=DB_PATH):
    """Compact plain-text diary block for the Gemini prompt, "" when the
    diary is empty (so the prompt simply omits the section).

    Kept deliberately small: the free tier limits requests per day, not
    tokens, so riding along on every call costs nothing extra - but a
    bloated block would slow replies and drown the format instructions
    at the end of the prompt.
    """
    now = now if now is not None else time.time()
    events = recent_events(limit=max_events, db_path=db_path)
    if not events:
        return ""

    lines = ["Witness diary - what JD has seen earlier (not necessarily visible right now):"]

    midnight = _local_midnight(now)
    today = _people_seen_since(midnight, db_path=db_path)
    if today:
        parts = []
        for person, first_ts, last_ts in today:
            span = _fmt_time(first_ts, now)
            if int(last_ts) != int(first_ts):
                span += " to " + _fmt_time(last_ts, now)
            parts.append(f"{_pool_label(person)} ({span})")
        lines.append("Seen today: " + "; ".join(parts))
    else:
        lines.append("No one seen yet today.")

    today_names = {person for person, _, _ in today}
    earlier = [
        (person, ts) for person, ts in _last_seen_per_person(db_path=db_path)
        if person not in today_names and ts < midnight
    ][:5]
    if earlier:
        lines.append(
            "Last seen on earlier days: "
            + "; ".join(f"{_pool_label(p)} ({_fmt_time(ts, now)})" for p, ts in earlier)
        )

    header_lines = list(lines)
    event_lines = [f"  {_fmt_time(ts, now)} {text}" for ts, _, _, _, text in events]

    def build(evts):
        return "\n".join(header_lines + ["Recent diary entries:"] + evts)

    # Trim whole entries (oldest first) rather than cutting mid-line.
    trimmed = False
    while event_lines and len(build(event_lines)) > max_chars:
        event_lines.pop(0)
        trimmed = True
    if trimmed:
        event_lines.insert(0, "  (older entries not shown)")
    return build(event_lines)
