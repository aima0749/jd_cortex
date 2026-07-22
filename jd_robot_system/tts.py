"""
Text-to-speech via ARC's SayEZBWait EZ-Script command, speaking through
JD's own onboard EZ-B v4 speaker hardware.

Confirmed working once the "Speech Synthesis" robot skill was added to
the ARC project (Project > Add Robot Skill > Audio > Speech Synthesis) -
that skill's own "Say (EZ-B v4 Speaker)" button proved the hardware and
audio routing both work. This should now work the same way over TCP.
"""


def _escape_for_ezscript(text):
    """EZ-Script strings use double quotes - escape any that appear in text."""
    return text.replace('"', "'")


def speak(arc, text):
    """Speaks a line via JD's onboard EZ-B speaker. Blocking - waits for
    ARC's reply so the next command doesn't fire mid-speech."""
    if not text:
        return
    safe_text = _escape_for_ezscript(text)
    command = f'SayEZBWait("{safe_text}")'
    try:
        response = arc.send_and_receive(command, timeout=20.0)
        if not response:
            print("  [TTS] no response from ARC within timeout (may still be speaking)")
    except (RuntimeError, OSError) as e:
        print(f"  [TTS ERROR] Failed to speak: {e}")