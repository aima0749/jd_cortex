"""
TCP server for the ARC custom plugin's control panel.

The plugin connects to 127.0.0.1:5005 and sends one command per line;
each gets one reply line back. This server runs as a daemon thread
inside main.py's process, so free text from the panel goes through the
exact same process_command() path as typed and spoken input - one brain,
one ARC connection, no forwarding queue.

Panel protocol (must match MainForm.cs):
    ping              -> OK: pong
    bridgedir         -> OK: <folder where the plugin writes frame.jpg>
    status            -> STATUS person=.. | object=.. | event=.. | gesture=..
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

# Where the C# plugin writes frame.jpg (it asks us via "bridgedir" on
# connect, so the two sides can never disagree about the path).
BRIDGE_DIR = os.environ.get("JD_BRIDGE_DIR",
                            os.path.join(_REPO_ROOT, "bridge"))

SCENE_STATE_PATH = os.environ.get(
    "JD_SCENE_STATE",
    os.path.join(_REPO_ROOT, "vision_pipeline", "scene_state.json"))
SCENE_STALE_SECS = 10.0

GESTURE_SCRIPT = os.path.join(_REPO_ROOT, "memory", "gesture_control.py")

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


def _last_diary_line():
    try:
        sys.path.insert(0, _REPO_ROOT)
        from memory import witness_store
        events = witness_store.recent_events(1)
        if events:
            return events[-1][4][:80]      # rows are (ts, kind, person, detail, text)
    except Exception:
        pass
    return None


def _status_line():
    person, obj = _read_scene()
    with _lock:
        event = _last_event
        gesture = "on" if _gesture_alive() else "off"
    if event == "-":
        diary = _last_diary_line()
        if diary:
            event = diary
    return ("STATUS person=%s | object=%s | event=%s | gesture=%s"
            % (person, obj, event, gesture))


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
    env = dict(os.environ)
    env["JD_BRIDGE_DIR"] = BRIDGE_DIR
    try:
        _gesture_proc = subprocess.Popen([sys.executable, GESTURE_SCRIPT],
                                         cwd=_REPO_ROOT, env=env)
    except Exception as e:
        return "ERR: could not start hand control (" + str(e) + ")"
    time.sleep(1.5)
    if not _gesture_alive():
        # it printed its own reason (usually a missing library) and died
        return ("ERR: hand control exited at startup - check the Python "
                "window for the reason (often: pip install opencv-python "
                '"mediapipe==0.10.21")')
    set_event("hand control on")
    return "OK: gesture mode on"


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
