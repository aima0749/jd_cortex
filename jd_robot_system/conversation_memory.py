

"""
Short-term rolling conversation memory. Keeps the last N exchanges in
memory during a session only - no file, no persistence across restarts.
Auto-resets completely to empty every AUTO_RESET_AFTER turns, so token
cost never creeps up even during a long single session.
"""


from collections import deque

MAX_TURNS = 6           # how many past exchanges to remember at once
AUTO_RESET_AFTER = 15    # after this many total exchanges, wipe memory and start fresh

_history = deque(maxlen=MAX_TURNS)
_turn_count = 0


def add_turn(user_text, jd_reply):
    global _turn_count
    _history.append((user_text[:80], jd_reply[:80]))
    _turn_count += 1

    if _turn_count >= AUTO_RESET_AFTER:
        clear()
        print("  [memory] Auto-reset - starting fresh from scratch.")


def get_history_block():
    if not _history:
        return ""
    lines = ["Recent conversation so far:"]
    for user_text, jd_reply in _history:
        lines.append(f'  Person: "{user_text}"')
        lines.append(f'  JD: "{jd_reply}"')
    return "\n".join(lines) + "\n"


def clear():
    global _turn_count
    _history.clear()
    _turn_count = 0