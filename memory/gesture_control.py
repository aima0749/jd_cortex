"""
Hand-gesture control for JD, run as its own process.

Frames come from a stationary camera - the laptop webcam - never from
JD's own camera. JD's camera moves when JD does, so a FORWARD gesture
would shake the view, lose the hand, and trip the safety STOP below:
the one gesture meant to make JD walk is the one that cancels itself.
A camera that doesn't move breaks that loop.

This classifies the hand with MediaPipe and sends the matching action
to ARC over its own TCP connection. panel_server starts and stops this
when the panel's hand-control button is pressed.

Gestures (same set the panel legend shows):
    fist=FORWARD  open hand=STOP  index left/right=turn  index down=SIT
    peace sign=WAVE  three fingers=STAND  index+pinky=PUSHUPS

Run it directly (same camera, same behaviour as the panel button):
    python memory/gesture_control.py
Logic checks without any camera or MediaPipe:
    python memory/gesture_control.py selftest
"""

import math
import os
import socket
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Which camera to gesture at. 0 is the built-in webcam; set
# JD_GESTURE_CAMERA if a USB camera enumerates first or the built-in one
# is already in use.
CAMERA_INDEX = int(os.environ.get("JD_GESTURE_CAMERA", "0"))

ARC_HOST = os.environ.get("JD_ARC_HOST", "127.0.0.1")
ARC_PORT = int(os.environ.get("JD_ARC_PORT", "6666"))

STABLE_FRAMES = 5        # a gesture must hold this many frames to count
POINT_MARGIN = 0.05
HAND_DIR_MARGIN = 0.05
MIRROR = True            # flip so "left on screen" is your left

# SAFETY: if the hand disappears while JD is walking or turning, stop him
# after this many hand-less frames instead of letting him walk forever.
NO_HAND_STOP_FRAMES = 15
MOTION_COMMANDS = {"FORWARD", "LEFT", "RIGHT"}

# What each committed gesture sends to ARC. WAVE/SIT/STAND/PUSHUPS use
# the Auto Position action names already verified by the command system
# (known_actions.py). Forward/Left/Right are the stock JD walking actions
# - VERIFY these three names against the ARC project on hardware day and
# correct them here if the project uses different ones.
ACTION_FOR = {
    "FORWARD": 'ControlCommand("Auto Position", AutoPositionAction, "Forward")',
    "LEFT":    'ControlCommand("Auto Position", AutoPositionAction, "Left")',
    "RIGHT":   'ControlCommand("Auto Position", AutoPositionAction, "Right")',
    "STOP":    'ControlCommand("Auto Position", "AutoPositionStop")',
    "WAVE":    'ControlCommand("Auto Position", AutoPositionAction, "Wave")',
    "SIT":     'ControlCommand("Auto Position", AutoPositionAction, "Sit Down")',
    "STAND":   'ControlCommand("Auto Position", AutoPositionAction, "Stand From Sit")',
    "PUSHUPS": 'ControlCommand("Auto Position", AutoPositionAction, "Pushups")',
}

FINGERS = {"index": (8, 6), "middle": (12, 10), "ring": (16, 14),
           "pinky": (20, 18)}
WRIST = 0
MIDDLE_MCP = 9

try:
    import cv2
    import mediapipe as mp
    if not hasattr(mp, "solutions"):
        # MediaPipe 0.10.30+ removed the classic Hands API this uses.
        raise ImportError(
            "this MediaPipe version (" + mp.__version__ + ") has no legacy "
            'solutions API. Fix:  pip install "mediapipe==0.10.21"')
    _MP_OK = True
    _IMPORT_ERR = ""
except Exception as _e:
    _MP_OK = False
    _IMPORT_ERR = str(_e)

_hands = None
_committed = "STOP"
_candidate = "STOP"
_streak = 0
_no_hand_streak = 0
_sock = None


# --- classification (identical logic to the tested original) ---------

def fingers_extended(lm):
    def d(a, b):
        return math.hypot(lm[a].x - lm[b].x, lm[a].y - lm[b].y)
    return {name: d(tip, WRIST) > d(pip, WRIST)
            for name, (tip, pip) in FINGERS.items()}


def classify_hand(lm):
    f = fingers_extended(lm)
    n = sum(f.values())

    if n >= 4:
        return "STOP"          # open palm is always stop
    if n == 0:
        return "FORWARD"

    if f["index"] and not (f["middle"] or f["ring"] or f["pinky"]):
        dx = lm[8].x - lm[5].x
        dy = lm[8].y - lm[5].y          # y grows DOWNWARD on screen
        if dy > POINT_MARGIN and dy > abs(dx):
            return "SIT"
        if dx < -POINT_MARGIN:
            return "LEFT"
        if dx > POINT_MARGIN:
            return "RIGHT"
        return "STOP"

    if f["index"] and f["middle"] and not (f["ring"] or f["pinky"]):
        return "WAVE"
    if f["index"] and f["middle"] and f["ring"] and not f["pinky"]:
        return "STAND"
    if f["index"] and f["pinky"] and not (f["middle"] or f["ring"]):
        return "PUSHUPS"
    return "STOP"


# --- sending to ARC ---------------------------------------------------

def _send(command_text):
    """Send one EZ-Script line to ARC, reconnecting once if the socket
    died. Never raises - losing ARC mid-gesture must not crash the loop."""
    global _sock
    for attempt in (0, 1):
        try:
            if _sock is None:
                _sock = socket.create_connection((ARC_HOST, ARC_PORT),
                                                 timeout=3)
                try:
                    _sock.recv(1024)      # ARC's greeting banner
                except OSError:
                    pass
            _sock.sendall((command_text + "\r\n").encode("utf-8"))
            return True
        except OSError as e:
            try:
                if _sock is not None:
                    _sock.close()
            except OSError:
                pass
            _sock = None
            if attempt == 1:
                print("[gesture] ARC send failed: " + str(e))
    return False


def send_action(cmd):
    line = ACTION_FOR.get(cmd)
    if line:
        _send(line)


# --- debounce (identical behaviour, send instead of file write) -------

def _commit(raw):
    global _committed, _candidate, _streak, _no_hand_streak

    if raw == "NO HAND":
        _no_hand_streak += 1
        if (_no_hand_streak >= NO_HAND_STOP_FRAMES
                and _committed in MOTION_COMMANDS):
            _committed = "STOP"
            print("[gesture] hand lost - SAFETY STOP")
            send_action("STOP")
    else:
        _no_hand_streak = 0

    if raw == _candidate:
        _streak = _streak + 1
    else:
        _candidate, _streak = raw, 1

    if (_streak >= STABLE_FRAMES
            and _candidate != _committed
            and _candidate != "NO HAND"):
        _committed = _candidate
        print("[gesture] COMMAND -> " + _committed)
        send_action(_committed)

    return _committed


# --- frames -----------------------------------------------------------

def step(frame):
    global _committed
    if MIRROR:
        frame = cv2.flip(frame, 1)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res = _hands.process(rgb)

    raw = "NO HAND"
    if res.multi_hand_landmarks:
        hand = res.multi_hand_landmarks[0]
        raw = classify_hand(hand.landmark)
        mp.solutions.drawing_utils.draw_landmarks(
            frame, hand, mp.solutions.hands.HAND_CONNECTIONS)

    committed = _commit(raw)
    cv2.putText(frame, "raw: " + raw, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
    cv2.putText(frame, "SENDING: " + committed, (10, 72),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 0), 3)
    return frame


def main():
    global _hands
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest()

    if not _MP_OK:
        print("[gesture] not available: " + _IMPORT_ERR)
        return 1

    _hands = mp.solutions.hands.Hands(model_complexity=0, max_num_hands=1,
                                      min_detection_confidence=0.6,
                                      min_tracking_confidence=0.5)
    send_action("STOP")                 # start from a known safe state

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("[gesture] could not open camera %d." % CAMERA_INDEX)
        print("[gesture] a camera can only be opened by one program at a "
              "time - if ARC's Camera skill is pointed at this same webcam, "
              "point ARC at JD's camera instead, or set JD_GESTURE_CAMERA "
              "to a different index.")
        return 1
    print("[gesture] watching camera %d - show a hand; q in the window "
          "quits." % CAMERA_INDEX)

    show = os.environ.get("JD_GESTURE_WINDOW", "on") != "off"
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            annotated = step(frame)
            if show:
                cv2.imshow("JD gesture control (q to quit)", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            else:
                time.sleep(0.03)
    except KeyboardInterrupt:
        pass
    finally:
        send_action("STOP")             # never leave JD walking
        try:
            _hands.close()
        except Exception:
            pass
        cap.release()
        if show:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
    return 0


# --- selftest: classifier and debounce, no camera, no MediaPipe -------

class _P:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _hand(extended, index_tip=None):
    """Synthetic landmarks: wrist at (0.5, 0.9), extended fingertips far
    from the wrist, curled ones close to it."""
    lm = [_P(0.5, 0.9) for _ in range(21)]
    lm[MIDDLE_MCP] = _P(0.5, 0.6)
    for name, (tip, pip) in FINGERS.items():
        lm[pip] = _P(0.5, 0.55)
        lm[tip] = _P(0.5, 0.2) if name in extended else _P(0.5, 0.7)
    lm[5] = _P(0.5, 0.5)                      # index knuckle
    if index_tip is not None:
        lm[8] = _P(*index_tip)
    return lm


def selftest():
    global _committed, _candidate, _streak, _no_hand_streak
    sent = []
    globals()["send_action"] = lambda cmd: sent.append(cmd)

    checks = []

    def check(label, ok):
        checks.append(ok)
        print("  [" + ("ok" if ok else "FAIL") + "] " + label)

    check("open palm is STOP",
          classify_hand(_hand({"index", "middle", "ring", "pinky"})) == "STOP")
    check("fist is FORWARD", classify_hand(_hand(set())) == "FORWARD")
    check("index pointing left turns LEFT",
          classify_hand(_hand({"index"}, index_tip=(0.3, 0.5))) == "LEFT")
    check("index pointing right turns RIGHT",
          classify_hand(_hand({"index"}, index_tip=(0.7, 0.5))) == "RIGHT")
    # pointing down means the wrist sits ABOVE the fingertip, so this one
    # is built by hand rather than with the palm-up helper
    down = [_P(0.5, 0.2) for _ in range(21)]      # wrist and curled tips high
    down[MIDDLE_MCP] = _P(0.5, 0.45)
    for name, (tip, pip) in FINGERS.items():
        down[pip] = _P(0.5, 0.45)
        down[tip] = _P(0.5, 0.3)                  # curled: closer to wrist
    down[5] = _P(0.5, 0.5)                        # index knuckle
    down[6] = _P(0.5, 0.6)                        # index pip, below knuckle
    down[8] = _P(0.5, 0.8)                        # index tip, well below
    check("index pointing down is SIT", classify_hand(down) == "SIT")
    check("peace sign is WAVE",
          classify_hand(_hand({"index", "middle"}, index_tip=(0.5, 0.2))) == "WAVE")
    check("three fingers is STAND",
          classify_hand(_hand({"index", "middle", "ring"},
                              index_tip=(0.5, 0.2))) == "STAND")
    check("index plus pinky is PUSHUPS",
          classify_hand(_hand({"index", "pinky"}, index_tip=(0.5, 0.2))) == "PUSHUPS")

    _committed, _candidate, _streak, _no_hand_streak = "STOP", "STOP", 0, 0
    sent.clear()
    for _ in range(STABLE_FRAMES - 1):
        _commit("FORWARD")
    check("a flicker shorter than the debounce sends nothing", sent == [])
    _commit("FORWARD")
    check("a held gesture commits and sends once", sent == ["FORWARD"])
    for _ in range(NO_HAND_STOP_FRAMES):
        _commit("NO HAND")
    check("losing the hand mid-walk sends the safety STOP",
          sent == ["FORWARD", "STOP"])

    _committed, _candidate, _streak, _no_hand_streak = "WAVE", "WAVE", 0, 0
    sent.clear()
    for _ in range(NO_HAND_STOP_FRAMES + 2):
        _commit("NO HAND")
    check("losing the hand while stationary sends nothing", sent == [])

    check("every command has an ARC action mapped",
          all(c in ACTION_FOR for c in
              ("FORWARD", "LEFT", "RIGHT", "STOP", "WAVE", "SIT", "STAND",
               "PUSHUPS")))

    print("\n%d passed, %d failed" % (sum(checks), len(checks) - sum(checks)))
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
