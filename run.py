"""
One launcher for the whole JD system.

Replaces start_jd.bat, which hardcoded one person's folder path and
started everything at once regardless of what was ready. This finds the
repo from its own location, so it works from any folder on any machine,
and starts the five processes in the order they actually depend on each
other.

    python run.py check     what's ready and what isn't - run this first
    python run.py           start everything
    python run.py --minimal ARC brain + witness memory only, no vision

Each process gets its own console window, because main.py asks which
input mode to use and the watchers print live status worth watching.
Ctrl+C here closes all of them.

Why the order matters: the vision pipeline has to load two YOLO models
and start writing scene_state.json before anything that reads it is
worth starting. Everything downstream tolerates a missing file, but
starting them early just means a screenful of "waiting" first.
"""

import os
import shutil
import socket
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable          # whichever interpreter ran this - venv included

ARC_HOST = "127.0.0.1"
ARC_PORT = 6666
PANEL_PORT = 5005

SCENE_STATE = os.path.join(REPO, "vision_pipeline", "scene_state.json")
SPEECH_QUEUE = os.path.join(REPO, "jd_robot_system", "speech_queue.json")
SNAPSHOT_REQ = os.path.join(REPO, "vision_pipeline", "snapshot_request.txt")

VISION_WAIT = 8.0            # YOLO load time before readers are worth starting


def _port_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------
# check: every question worth answering before a session, in one place
# ---------------------------------------------------------------------

def _ok(label, detail=""):
    print(f"  [ok]   {label}" + (f" - {detail}" if detail else ""))
    return True


def _warn(label, detail=""):
    print(f"  [warn] {label}" + (f" - {detail}" if detail else ""))
    return True


def _bad(label, detail=""):
    print(f"  [MISS] {label}" + (f" - {detail}" if detail else ""))
    return False


def check():
    print("JD system check\n")
    print(f"  repo:   {REPO}")
    print(f"  python: {sys.version.split()[0]} ({PY})\n")

    blocking = []

    print("Libraries")
    for mod, why in [("cv2", "vision + gestures"),
                     ("mediapipe", "hand gestures"),
                     ("requests", "Gemini"),
                     ("sounddevice", "microphone"),
                     ("sherpa_onnx", "speech to text"),
                     ("ultralytics", "vision pipeline"),
                     ("face_recognition", "face names")]:
        try:
            __import__(mod)
            _ok(mod)
        except Exception as e:
            # Not just ImportError: sounddevice raises OSError when the
            # PortAudio backend is missing, and a half-installed library
            # would otherwise crash the check instead of reporting itself.
            if not _bad(mod, f"{why} ({type(e).__name__})"):
                blocking.append(mod)

    print("\nModels and data")
    enc = os.path.join(REPO, "setup", "known_encodings.pkl")
    if os.path.exists(enc):
        _ok("known_encodings.pkl")
    else:
        _warn("known_encodings.pkl", "run setup/enroll_faces.py - nobody will be named")

    parakeet = os.path.join(REPO, "voice_model", "parakeet")
    # tokens.txt is committed to the repo, so "folder is non-empty" is not
    # evidence of anything - the .onnx weights are what actually matter and
    # they are deliberately not tracked.
    onnx = []
    if os.path.isdir(parakeet):
        onnx = [f for f in os.listdir(parakeet) if f.lower().endswith(".onnx")]
    if onnx:
        _ok("parakeet model", f"{len(onnx)} .onnx file(s)")
    else:
        _warn("parakeet model", "no .onnx weights - voice input and the "
                                "panel mic won't work")

    for name in ("yolov8m.pt", "yolov8m-pose.pt"):
        path = os.path.join(REPO, "vision_pipeline", name)
        if os.path.exists(path):
            _ok(name, f"{os.path.getsize(path) / 1e6:.0f} MB")
        else:
            _warn(name, "will download on first run")

    print("\nGemini keys")
    keys = [v for v in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")
            if os.environ.get(v, "").strip() not in ("", "PUT_YOUR_KEY_HERE")]
    if keys:
        _ok(f"{len(keys)} key(s) set", ", ".join(keys))
        if len(keys) == 1:
            print("         one key is ~20 requests/day/model, shared by "
                  "conversation, alerts and ambient")
    else:
        _warn("no key in the environment", "config.py's value will be used")

    print("\nPorts")
    if _port_open(ARC_HOST, ARC_PORT):
        _ok(f"ARC on {ARC_PORT}")
    else:
        _bad(f"ARC on {ARC_PORT}", "open ARC, load the project, add the TCP "
                                   "script server skill")
        blocking.append("arc")

    if _port_open(ARC_HOST, PANEL_PORT):
        _warn(f"port {PANEL_PORT} already in use",
              "another main.py is probably still running")
    else:
        _ok(f"panel port {PANEL_PORT} free")

    print("\nLeftovers from a previous run")
    stale = [p for p in (SCENE_STATE, SPEECH_QUEUE, SNAPSHOT_REQ)
             if os.path.exists(p)]
    if stale:
        for p in stale:
            age = time.time() - os.path.getmtime(p)
            _warn(os.path.basename(p), f"{age / 60:.0f} min old - will be swept")
    else:
        _ok("nothing stale")

    print("")
    if blocking:
        print("NOT READY: " + ", ".join(blocking))
        return 1
    print("Ready to start.")
    return 0


# ---------------------------------------------------------------------
# start
# ---------------------------------------------------------------------

def sweep():
    """Removes files that describe a world that no longer exists. A stale
    scene_state makes the panel show people who left hours ago; a stale
    speech_queue makes JD announce them on startup."""
    for path in (SCENE_STATE, SPEECH_QUEUE, SNAPSHOT_REQ):
        try:
            os.remove(path)
            print(f"  swept {os.path.basename(path)}")
        except OSError:
            pass


def spawn(title, script, cwd):
    """Own console window per process - main.py prompts for input mode and
    the watchers print live status."""
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return subprocess.Popen([PY, script], cwd=cwd, creationflags=flags)


def start(minimal=False):
    if not _port_open(ARC_HOST, ARC_PORT):
        print(f"ARC is not listening on {ARC_HOST}:{ARC_PORT}.")
        print("Open ARC, load the JD project, and add the TCP script server "
              "skill, then run this again.")
        print("(python run.py check  lists everything else that's missing)")
        return 1

    print("Sweeping stale files...")
    sweep()

    jrs = os.path.join(REPO, "jd_robot_system")
    procs = []

    if not minimal:
        print("\nStarting vision pipeline...")
        procs.append(("vision", spawn("JD Vision", "01_full_pipeline.py",
                                      os.path.join(REPO, "vision_pipeline"))))
        print(f"  waiting {VISION_WAIT:.0f}s for models to load...")
        time.sleep(VISION_WAIT)

    print("Starting witness recorder...")
    procs.append(("recorder", spawn("JD Recorder",
                                    os.path.join("memory", "witness_recorder.py"),
                                    REPO)))

    print("Starting command system...")
    procs.append(("brain", spawn("JD Brain", "main.py", jrs)))

    if not minimal:
        print("Starting surveillance watcher...")
        procs.append(("surveillance", spawn("JD Surveillance",
                                            "surveillance_watcher.py", jrs)))
        print("Starting ambient watcher...")
        procs.append(("ambient", spawn("JD Ambient", "ambient_watcher.py", jrs)))

    print(f"\n{len(procs)} process(es) running. Answer the input-mode prompt "
          f"in the JD Brain window.")
    print("Ctrl+C here stops all of them.\n")

    try:
        while True:
            for name, p in procs:
                if p.poll() is not None:
                    print(f"  [{name}] exited with code {p.returncode} - "
                          f"check its window for the reason")
                    procs = [(n, q) for n, q in procs if q is not p]
                    break
            if not procs:
                print("Everything has exited.")
                return 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping...")
        for name, p in procs:
            if p.poll() is None:
                p.terminate()
        time.sleep(2.0)
        for name, p in procs:
            if p.poll() is None:
                p.kill()
        print("Stopped.")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "check":
        sys.exit(check())
    sys.exit(start(minimal=(arg == "--minimal")))