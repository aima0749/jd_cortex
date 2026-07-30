"""
Text-to-speech via ARC, speaking through JD's own onboard EZ-B v4 speaker.
Only main.py should ever call this directly. surveillance_watcher.py uses
speech_queue.request_speech() instead - keeps exactly ONE process/
connection driving JD's speaker.
"""
import threading

_lock = threading.Lock()
speaking_flag = threading.Event()  # set while JD is actively speaking


def _escape_for_ezscript(text):
    return text.replace('"', "'")


def speak(arc, text):
    """Speaks a line via JD's onboard EZ-B speaker. Blocking - waits for
    ARC's reply so the next command doesn't fire mid-speech. Sets
    speaking_flag for the duration, so listen_for_command() can refuse
    to start recording while JD is still talking."""
    if not text:
        return

    with _lock:
        speaking_flag.set()
        try:
            safe_text = _escape_for_ezscript(text)
            command = f'SayWait("{safe_text}")'
            try:
                response = arc.send_and_receive(command, timeout=20.0)
                if not response:
                    print("  [TTS] no response from ARC within timeout (may still be speaking)")
            except (RuntimeError, OSError) as e:
                print(f"  [TTS ERROR] Failed to speak: {e}")
        finally:
            speaking_flag.clear()