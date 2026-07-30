"""
Hold-to-talk speech for the ARC panel's microphone button.

The panel sends "listen start" when the button goes down and "listen
stop" when it's released; panel_server calls record_start()/record_stop()
here and hands the transcript to the brain. Push-to-talk on purpose: a
competition hall is loud, wake words false-trigger, and a button always
works.

Transcription is the same offline stack as voice input - NVIDIA Parakeet
TDT via sherpa-onnx, from the shared voice_model/parakeet folder - so the
project carries one speech model, set up once for both.

Test the microphone on its own:      python panel_listen.py
List input devices (pick the mic):   python panel_listen.py devices
"""

import difflib
import os
import re
import threading

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PARAKEET_DIR = os.path.join(_REPO_ROOT, "voice_model", "parakeet")
KNOWN_DIR = os.path.join(_REPO_ROOT, "setup", "known_faces")

SAMPLE_RATE = 16000

# None = Windows' default microphone. If that's the wrong one (a webcam
# mic, a dead headset jack), run  python panel_listen.py devices  and set
# the environment variable JD_MIC_DEVICE to the right number.
MIC_DEVICE = os.environ.get("JD_MIC_DEVICE")
MIC_DEVICE = int(MIC_DEVICE) if MIC_DEVICE not in (None, "") else None

CLIP_LEVEL = 0.98    # peak near 1.0 means the mic is clipping: loud parts
                     # flatten into distortion and the model mishears
MIN_LEVEL = 0.02     # below this the clip is basically silence; models
                     # invent words when fed silence, so refuse instead
TARGET_LEVEL = 0.35  # quiet-but-real speech gets boosted to about this
NAME_FIX_CUTOFF = 0.8  # strict on purpose - "correcting" ordinary words
                       # into names is worse than mishearing one

SAVE_LAST_WAV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "last_heard.wav")

_model = None
_lock = threading.Lock()
_capture = None

try:
    import numpy as np
    import sounddevice as sd
    _DEPS_OK = True
    _DEPS_ERR = ""
except Exception as e:
    _DEPS_OK = False
    _DEPS_ERR = str(e)

try:
    import sherpa_onnx
    _STT_OK = True
except Exception as e:
    sherpa_onnx = None
    _STT_OK = False
    if not _DEPS_ERR:
        _DEPS_ERR = str(e)


def is_ready():
    if not _DEPS_OK or not _STT_OK:
        return False
    return os.path.exists(os.path.join(PARAKEET_DIR, "encoder.int8.onnx"))


def is_loaded():
    return _model is not None


def why_not():
    if _DEPS_ERR:
        return _DEPS_ERR + " (fix: pip install sherpa-onnx sounddevice)"
    if not os.path.exists(os.path.join(PARAKEET_DIR, "encoder.int8.onnx")):
        return ("model files missing - expected encoder.int8.onnx (and "
                "friends) in " + os.path.abspath(PARAKEET_DIR))
    return ""


def load():
    """Bring the Parakeet model into memory. ~620MB from disk, so
    panel_server preloads it at startup - the first button press must
    never pay that cost mid-demo."""
    global _model
    if not is_ready():
        print("[listen] not available: " + why_not())
        return False
    with _lock:
        if _model is None:
            print("[listen] loading the Parakeet speech model (620MB from "
                  "disk - not frozen, just loading)...")
            _model = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=os.path.join(PARAKEET_DIR, "encoder.int8.onnx"),
                decoder=os.path.join(PARAKEET_DIR, "decoder.int8.onnx"),
                joiner=os.path.join(PARAKEET_DIR, "joiner.int8.onnx"),
                tokens=os.path.join(PARAKEET_DIR, "tokens.txt"),
                num_threads=2,
                sample_rate=SAMPLE_RATE,
                feature_dim=80,
                decoding_method="greedy_search",
                model_type="nemo_transducer",
            )
            print("[listen] speech model ready.")
    return True


def list_devices():
    if not _DEPS_OK:
        print("[listen] not available: " + _DEPS_ERR)
        return
    print("Input devices (set JD_MIC_DEVICE to the number on the left):")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            default = ""
            try:
                if i == sd.default.device[0]:
                    default = "   <-- current default"
            except Exception:
                pass
            print("  " + str(i) + ": " + d["name"] + default)


def record_start():
    """Begin capturing. Returns straight away - audio piles up in the
    background until record_stop()."""
    global _capture
    if not _DEPS_OK:
        return False
    if _capture is not None:
        return True                     # double press; already going
    chunks = []

    def _cb(indata, n, t, status):
        chunks.append(indata.copy())

    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                dtype="float32", device=MIC_DEVICE,
                                blocksize=int(SAMPLE_RATE * 0.1),
                                callback=_cb)
        stream.start()
    except Exception as e:
        print("[listen] microphone error: " + str(e))
        return False
    _capture = {"stream": stream, "chunks": chunks}
    print("[listen] recording (button held)...")
    return True


def record_stop():
    """Stop capturing and hand back everything that was said."""
    global _capture
    if _capture is None:
        return np.zeros(0, dtype=np.float32) if _DEPS_OK else None
    cap = _capture
    _capture = None
    try:
        cap["stream"].stop()
        cap["stream"].close()
    except Exception:
        pass
    if not cap["chunks"]:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(cap["chunks"]).flatten()
    print("[listen] recorded %.1fs" % (len(audio) / float(SAMPLE_RATE)))
    return audio


def transcribe_buffer(audio):
    if audio is None or len(audio) == 0:
        print("[listen] nothing recorded.")
        return ""
    if len(audio) < SAMPLE_RATE * 0.3:
        print("[listen] too short - button tapped rather than held?")
        return ""

    ok, audio, problem = _level_ok(audio)
    _save_wav(audio)
    if not ok:
        print("[listen] " + problem)
        return ""

    text = _transcribe_parakeet(audio)
    text = _fix_names(text)
    if text:
        print("[listen] heard: " + text)
    else:
        print("[listen] heard nothing.")
    return text


def _level_ok(audio):
    """Check the mic actually captured speech, and normalise the volume.
    Returns (ok, audio, message)."""
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    rms = float(np.sqrt((audio ** 2).mean())) if audio.size else 0.0
    print("[listen] mic level: peak=%.3f  rms=%.4f" % (peak, rms))

    if peak >= CLIP_LEVEL:
        print("[listen] WARNING: microphone is CLIPPING (peak %.2f) - sit "
              "further back, or lower the input volume in Windows "
              "Settings > Sound > Input." % peak)

    if peak < MIN_LEVEL:
        return False, audio, (
            "microphone is silent (peak %.3f). Check the right mic is "
            "selected (python panel_listen.py devices), that it isn't "
            "muted, and that no other app is holding it." % peak)

    if peak < TARGET_LEVEL:
        gain = min(TARGET_LEVEL / peak, 8.0)   # never amplify hiss into "speech"
        audio = audio * gain
        print("[listen] quiet input, boosted x%.1f" % gain)

    return True, audio, ""


def _save_wav(audio, path=SAVE_LAST_WAV):
    """Save what the mic heard. Playing this back instantly tells you
    whether a bad transcript is a bad microphone or a bad model."""
    try:
        import wave
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
    except Exception as e:
        print("[listen] could not save wav: " + str(e))


def known_names():
    """Every name JD might hear: the enrolled photos (people JD can
    recognise, even with no diary entries yet) plus anyone already in
    the witness diary."""
    names = set()
    try:
        for f in os.listdir(KNOWN_DIR):
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                n = os.path.splitext(f)[0]
                n = re.sub(r"_\d+$", "", n)        # name1_2.jpg -> name1
                n = n.replace("_", " ").strip().title()
                if n:
                    names.add(n)
    except Exception:
        pass
    try:
        import sqlite3
        import sys
        sys.path.insert(0, _REPO_ROOT)
        from memory import witness_store
        con = sqlite3.connect(witness_store.DB_PATH)
        try:
            rows = con.execute(
                "SELECT DISTINCT person FROM events "
                "WHERE person IS NOT NULL AND person != ''").fetchall()
        finally:
            con.close()
        for (n,) in rows:
            if n and n.lower() not in ("someone", "unknown"):
                names.add(str(n).title())
    except Exception:
        pass
    return sorted(names)


def _transcribe_parakeet(audio):
    if not load() or _model is None:
        return ""
    try:
        stream = _model.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio.astype(np.float32))
        _model.decode_stream(stream)
        return stream.result.text.strip()
    except Exception as e:
        print("[listen] transcribe error: " + str(e))
        return ""


def _fix_names(text):
    """Snap near-misses back to real names: the model often returns a
    close-but-wrong spelling of an enrolled name. Deliberately strict -
    turning an ordinary word into a name would be worse than mishearing
    one."""
    names = known_names()
    if not names or not text:
        return text
    lower_names = {n.lower(): n for n in names}
    out = []
    for word in text.split():
        bare = re.sub(r"[^A-Za-z']", "", word)
        suffix = ""
        if bare.lower().endswith("'s"):    # "name1's" stays possessive
            suffix = bare[-2:]
            bare = bare[:-2]
        if bare.lower() in lower_names:
            proper = lower_names[bare.lower()]
            if bare != proper:
                word = word.replace(bare + suffix, proper + suffix)
            out.append(word)
            continue
        if len(bare) < 4:
            out.append(word)
            continue
        m = difflib.get_close_matches(bare.lower(), list(lower_names.keys()),
                                      n=1, cutoff=NAME_FIX_CUTOFF)
        if m:
            fixed = lower_names[m[0]]
            print("[listen] name fix: '" + bare + suffix + "' -> '"
                  + fixed + suffix + "'")
            word = word.replace(bare + suffix, fixed + suffix)
        out.append(word)
    return " ".join(out)


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "devices":
        list_devices()
        return
    print("=== panel hold-to-talk test ===")
    if not is_ready():
        print("Not ready: " + why_not())
        return
    load()
    input("Press Enter, speak, then press Enter again to stop... ")
    record_start()
    input()
    text = transcribe_buffer(record_stop())
    print("Result: " + (repr(text) if text else "(nothing)"))


if __name__ == "__main__":
    main()
