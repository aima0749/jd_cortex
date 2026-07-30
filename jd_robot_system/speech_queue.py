"""
Simple file-based speech request queue. Lets a separate process
(surveillance_watcher.py) ask main.py to say something, WITHOUT opening
its own ARC connection - only main.py ever talks to ARC for speech now.
This is the permanent fix for the "two processes both driving JD's
speaker" problem: exactly one connection, one owner, no more fragile
cross-process locking around two live sockets.
"""
import json
import os
import tempfile

# Anchored to THIS file's folder, not the launch directory - main.py runs
# from jd_robot_system/ while witness_recorder.py runs from the repo root,
# and both must agree on the same queue file or requests silently go to a
# file nobody reads.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_PATH = os.path.join(_BASE_DIR, "speech_queue.json")


def request_speech(text):
    """Called by OTHER processes (e.g. surveillance_watcher.py) to ask
    main.py to speak something. Just appends to a small JSON file - no
    ARC connection needed here at all."""
    messages = []
    if os.path.exists(QUEUE_PATH):
        try:
            with open(QUEUE_PATH, "r") as f:
                messages = json.load(f)
        except (json.JSONDecodeError, OSError):
            messages = []

    messages.append(text)

    # Temp-file-then-rename, same as the vision pipeline's scene_state
    # write, so main.py can never read a half-written queue file.
    try:
        with tempfile.NamedTemporaryFile("w", dir=_BASE_DIR, delete=False,
                                         suffix=".tmp") as tmp_f:
            json.dump(messages, tmp_f)
            tmp_path = tmp_f.name
        os.replace(tmp_path, QUEUE_PATH)
    except OSError as e:
        print(f"  [speech_queue] failed to write request: {e}")


def pop_pending_messages():
    """Called by main.py to collect and clear any pending speech requests
    from other processes. Returns a list (empty if none)."""
    if not os.path.exists(QUEUE_PATH):
        return []

    try:
        with open(QUEUE_PATH, "r") as f:
            messages = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    try:
        os.remove(QUEUE_PATH)
    except OSError:
        pass

    return messages if isinstance(messages, list) else []