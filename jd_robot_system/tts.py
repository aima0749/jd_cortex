"""
Text-to-speech via ARC. Only main.py should ever call this directly;
witness_recorder.py and any other process use speech_queue.request_speech()
instead - keeps exactly ONE process/connection driving JD's speaker.

Where the voice comes out is controlled by the JD_SPEAK_TARGET environment
variable:
    ezb (default) - JD's onboard EZ-B v4 chest speaker, via SayEZBWait()
    pc            - the computer's speakers, via SayWait()
Both are the blocking variants on purpose: ARC replies only when the line
has finished, so the next queued line can never start mid-speech.
"""
import os
import threading

_lock = threading.Lock()
speaking_flag = threading.Event()  # set while JD is actively speaking

SPEAK_TARGET = os.environ.get("JD_SPEAK_TARGET", "ezb").strip().lower()
_SPEAK_COMMANDS = {"ezb": "SayEZBWait", "pc": "SayWait"}
_SPEAK_COMMAND = _SPEAK_COMMANDS.get(SPEAK_TARGET, "SayEZBWait")


def _escape_for_ezscript(text):
    # Double quotes would close the EZScript string early; a trailing
    # backslash makes ARC's parser choke on the closing quote entirely.
    text = text.replace('"', "'").replace("\n", " ").replace("\r", " ")
    return text.rstrip("\\").strip()


def speak(arc, text):
    """Speaks a line via ARC. Blocking - waits for ARC's reply so the
    next command doesn't fire mid-speech. Sets speaking_flag for the
    duration, so listen_for_command() can refuse to start recording
    while JD is still talking."""
    if not text:
        return

    with _lock:
        speaking_flag.set()
        try:
            safe_text = _escape_for_ezscript(text)
            if not safe_text:
                return
            command = f'{_SPEAK_COMMAND}("{safe_text}")'
            try:
                response = arc.send_and_receive(command, timeout=20.0)
                if not response:
                    print("  [TTS] no response from ARC within timeout (may still be speaking)")
            except (RuntimeError, OSError) as e:
                print(f"  [TTS ERROR] Failed to speak: {e}")
        finally:
            speaking_flag.clear()
