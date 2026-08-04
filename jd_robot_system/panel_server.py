"""
TCP server for the ARC custom plugin's control panel.

The plugin connects to 127.0.0.1:5005 and sends one command per line;
each gets one reply line back. This server runs as a daemon thread
inside main.py's process, so free text from the panel goes through the
exact same process_command() path as typed and spoken input - one brain,
one ARC connection, no forwarding queue.

Panel protocol (must match MainForm.cs):
    ping              -> OK: pong
    status            -> STATUS person=.. | object=.. | event=.. | gesture=..
                         (a trailing "| gemini N/M ok" segment carries the
                         API usage counter; segments without '=' are extras)
    diary [n]         -> DIARY hh:mm text ;; hh:mm text ...   (oldest first)
    alerts [n]        -> ALERTS today=N ;; hh:mm text ;; ...   (oldest first)
    gesture on|off    -> start/stop the hand-control subprocess
    listen start/stop -> hold-to-talk recording via panel_listen
    stop              -> shut the whole brain down (panel confirms first)
    anything else     -> a question or command for the brain
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time

import panel_listen

_HOST = "127.0.0.1"
_PORT = 5005

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Kept for older plugin builds that still ask "bridgedir" on connect;
# nothing on the Python side reads or writes this folder anymore.
BRIDGE_DIR = os.environ.get("JD_BRIDGE_DIR",
                            os.path.join(_REPO_ROOT, "bridge"))

SCENE_STATE_PATH = os.environ.get(
    "JD_SCENE_STATE",
    os.path.join(_REPO_ROOT, "vision_pipeline", "scene_state.json"))
SCENE_STALE_SECS = 10.0

GESTURE_SCRIPT = os.path.join(_REPO_ROOT, "memory", "gesture_control.py")

# surveillance_watcher opens this with a bare relative name, so it lands
# in whatever folder the watcher was started from. run.py starts it from
# jd_robot_system, which is where this file lives too - anchoring here
# rather than to the launch directory keeps the panel pointed at the same
# file no matter how the panel's own process was started.
ACTIVITY_LOG_PATH = os.environ.get(
    "JD_ACTIVITY_LOG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "activity_log.txt"))
SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "snapshots")

# Every verb the panel protocol uses, matched or not. Kept next to the
# handler so adding a command here is the same edit as implementing it.
_RESERVED = {"ping", "status", "diary", "alerts", "gesture", "listen",
             "stop", "bridgedir", "snapshots", "quota"}

_lock = threading.Lock()
_respond_fn = None                # main.py registers process_command here
_shutdown_fn = None               # main.py registers a clean shutdown here
_last_event = "-"                 # most recent thing worth showing on the panel
_gesture_proc = None


def register(respond_fn, shutdown_fn):
    global _respond_fn, _shutdown_fn
    _respond_fn = respond_fn
    _shutdown_fn = shutdown_fn


def set_event(text):
    """Anything may publish a short 'last event' line for the panel."""
    global _last_event
    with _lock:
        _last_event = (text or "-")[:80]


# ---------------------------------------------------------------------
# status: read the world directly rather than routing through the brain,
# so the card stays live even while Gemini is mid-answer.
# ---------------------------------------------------------------------

def _read_scene():
    """person/object strings from the vision pipeline's scene_state.json, or dashes when
    the file is missing, unreadable, or stale."""
    try:
        with open(SCENE_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return "-", "-"
    if time.time() - float(state.get("timestamp", 0)) > SCENE_STALE_SECS:
        return "-", "-"

    named, unknowns, holding = [], 0, "-"
    for info in (state.get("people") or {}).values():
        name = (info.get("name") or "").strip().lower()
        if not name or name in ("unknown", "unknown person"):
            unknowns += 1
            continue
        named.append(name)
        if holding == "-" and info.get("holding"):
            holding = str(info["holding"])
    parts = sorted(set(named))
    if unknowns:
        parts.append("someone" if unknowns == 1 else "%d people" % unknowns)
    person = ", ".join(parts) if parts else "-"
    return person, holding


def _recent_diary(limit):
    """Rows straight from the witness diary, oldest first, or []."""
    try:
        sys.path.insert(0, _REPO_ROOT)
        from memory import witness_store
        return witness_store.recent_events(limit)
    except Exception:
        return []


def _last_diary_line():
    events = _recent_diary(1)
    if events:
        return events[-1][4][:80]          # rows are (ts, kind, person, detail, text)
    return None


def _diary_reply(limit):
    """One line the panel can split on ' ;; ' - the protocol is one reply
    line per command, so a list has to travel flat."""
    events = _recent_diary(limit)
    if not events:
        return "DIARY -"
    parts = []
    for ts, _kind, _person, _detail, text in events:
        stamp = time.strftime("%H:%M", time.localtime(ts))
        clean = " ".join(str(text).split())        # no newlines, no runs
        parts.append(stamp + " " + clean[:70])
    return "DIARY " + " ;; ".join(parts)


def _alerts_reply(limit):
    """Tail of the surveillance log. Reports a count of log ENTRIES today
    rather than a count of people: the watcher keys off tracker ids, and
    those get reassigned freely, so one visitor can produce several
    entries. Saying 'entries' keeps the panel honest about that."""
    try:
        with open(ACTIVITY_LOG_PATH, "r", encoding="utf-8",
                  errors="replace") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return "ALERTS today=0"

    today = time.strftime("%Y-%m-%d")
    todays = [ln for ln in lines if ln.startswith("[" + today)]
    parts = ["today=%d" % len(todays)]

    for line in (todays or lines)[-limit:]:
        stamp, text = "", line
        if line.startswith("[") and "]" in line:
            head, text = line[1:].split("]", 1)
            stamp = head[11:16]                # HH:MM out of the full date
        clean = " ".join(text.split())
        parts.append((stamp + " " + clean).strip()[:70])
    return "ALERTS " + " ;; ".join(parts)


def _snapshot_count():
    try:
        return len([f for f in os.listdir(SNAPSHOT_DIR)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))])
    except OSError:
        return 0


def _status_line():
    person, obj = _read_scene()
    with _lock:
        event = _last_event
        gesture = "on" if _gesture_alive() else "off"
    if event == "-":
        diary = _last_diary_line()
        if diary:
            event = diary
    try:
        import gemini_brain
        quota = " | " + gemini_brain.usage_summary()
    except Exception:
        quota = ""      # the panel must never fail over a diagnostic
    return ("STATUS person=%s | object=%s | event=%s | gesture=%s%s"
            % (person, obj, event, gesture, quota))


# ---------------------------------------------------------------------
# gesture: a subprocess, so MediaPipe never loads inside the brain and a
# crash there can't take conversation down with it.
# ---------------------------------------------------------------------

def _gesture_alive():
    return _gesture_proc is not None and _gesture_proc.poll() is None


def _gesture_on():
    global _gesture_proc
    if _gesture_alive():
        return "OK: gesture mode on"
    try:
        # Captured, not inherited: this subprocess has no console of its
        # own, so anything it prints on the way out would otherwise
        # vanish and the panel button would look like it did nothing.
        _gesture_proc = subprocess.Popen(
            [sys.executable, GESTURE_SCRIPT], cwd=_REPO_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace")
    except Exception as e:
        return "ERR: could not start hand control (" + str(e) + ")"
    time.sleep(2.0)
    if not _gesture_alive():
        reason = _gesture_exit_reason()
        return "ERR: hand control quit at startup - " + reason
    set_event("hand control on")
    return "OK: gesture mode on"


def _gesture_exit_reason():
    """The most useful line the dead subprocess printed. Its own error
    text is better than anything guessable from out here."""
    try:
        out = _gesture_proc.stdout.read() if _gesture_proc.stdout else ""
    except Exception:
        out = ""
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    # skip MediaPipe/TensorFlow's startup noise, which is never the cause
    noise = ("INFO:", "WARNING: All log", "W0000", "I0000")
    useful = [ln for ln in lines if not ln.startswith(noise)]
    if useful:
        return " ".join(useful[-2:])[:200]
    return ("no output - most often the webcam is already in use "
            "(ARC's Camera skill holds it while the vision pipeline runs)")


def _gesture_off():
    global _gesture_proc
    if _gesture_alive():
        _gesture_proc.terminate()
        try:
            _gesture_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _gesture_proc.kill()
    _gesture_proc = None
    set_event("hand control off")
    return "OK: gesture mode off"


# ---------------------------------------------------------------------
# the protocol
# ---------------------------------------------------------------------

def _handle(cmd):
    cmd = cmd.strip()
    low = cmd.lower()

    if low == "ping":
        return "OK: pong"

    if low == "bridgedir":
        try:
            os.makedirs(BRIDGE_DIR, exist_ok=True)
        except OSError:
            pass
        return "OK: " + BRIDGE_DIR

    if low == "status":
        return _status_line()

    if low.startswith("alerts"):
        arg = low[6:].strip()
        try:
            limit = max(1, min(int(arg), 20)) if arg else 4
        except ValueError:
            limit = 4
        return _alerts_reply(limit)

    if low.startswith("diary"):
        arg = low[5:].strip()
        try:
            limit = max(1, min(int(arg), 20)) if arg else 8
        except ValueError:
            limit = 8
        return _diary_reply(limit)

    if low == "gesture on":
        return _gesture_on()

    if low == "gesture off":
        return _gesture_off()

    if low == "listen start":
        if not panel_listen.is_ready():
            return "ERR: " + panel_listen.why_not()
        set_event("listening...")
        if panel_listen.record_start():
            return "OK: recording"
        return "ERR: could not open the microphone"

    if low == "listen stop":
        audio = panel_listen.record_stop()
        text = panel_listen.transcribe_buffer(audio)
        if not text:
            set_event("didn't catch that")
            return "OK: (didn't catch that - hold the button and try again)"
        set_event("heard: " + text)
        reply = _ask_brain(text)
        return 'OK: "' + text + '"  ->  ' + reply

    if low == "stop":
        threading.Thread(target=_shutdown_later, daemon=True).start()
        return "OK: stopping"

    if cmd == "":
        return "UNKNOWN: (empty)"

    # Anything that LOOKS like a panel command but wasn't matched above is
    # refused, not forwarded. A newer plugin talking to an older server
    # would otherwise have its polling commands answered by Gemini - once
    # every couple of seconds, burning the daily quota and making JD act
    # on them. Free text still reaches the brain; protocol words never do.
    first = low.split()[0]
    if first in _RESERVED:
        return ("UNKNOWN: '" + first + "' is a panel command this brain "
                "doesn't know - the plugin is newer than the Python side.")

    return "OK: " + _ask_brain(cmd)


def _ask_brain(text):
    if _respond_fn is None:
        return "JD's brain isn't fully started yet."
    try:
        reply = _respond_fn(text)
    except Exception as e:
        return "something went wrong: " + str(e)
    return reply if reply else "Okay."


def _shutdown_later():
    # let the reply reach the panel before the process goes away
    time.sleep(0.5)
    _gesture_off()
    if _shutdown_fn is not None:
        _shutdown_fn()
    else:
        os._exit(0)


def _serve():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((_HOST, _PORT))
    except OSError as err:
        print("[panel] could NOT open port %d (%s)." % (_PORT, err))
        print("[panel] Is another copy of main.py already running?")
        return
    s.listen(1)
    print("[panel] ARC panel server on %s:%d" % (_HOST, _PORT))
    while True:
        conn, _addr = s.accept()
        try:
            with conn:
                buf = b""
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        reply = _handle(line.decode("utf-8", errors="replace"))
                        conn.sendall((reply + "\n").encode("utf-8"))
        except Exception as err:
            # one bad client drops; the server keeps accepting
            print("[panel] client error: " + str(err))


def start():
    threading.Thread(target=_serve, daemon=True).start()
    # Load the speech model now, in the background, not on the first
    # button press - someone holding "Listening..." while 620 MB loads
    # from disk looks exactly like a broken microphone.
    if panel_listen.is_ready():
        threading.Thread(target=panel_listen.load, daemon=True).start()
    else:
        print("[panel] hold-to-talk unavailable: " + panel_listen.why_not())