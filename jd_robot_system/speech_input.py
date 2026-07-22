"""
Voice input via ARC's own Speech Recognition skill, which listens through
your laptop's microphone (set up inside ARC itself, via its "Setup
Microphone" button - not a separate Python microphone library). This
module just polls the $SpeechPhrase variable that ARC updates whenever it
recognizes something, over the same TCP connection used for everything
else. No flaky unofficial Google endpoint, no separate audio stack.

Requires: ARC's Speech Recognition skill must be running/enabled in your
ARC project for this to receive anything - that part is configured inside
ARC, not here.
"""
from config import SPEECH_POLL_INTERVAL
import time

_last_phrase = [None]


def _clean_response(raw_text):
    """ARC's TCP console can mix its own command acknowledgment (e.g. an
    'OK') in with the actual Print() output, not cleanly separated. We ask
    ARC to print a distinctive marker alongside the value, then only ever
    trust text found after that marker - anything else (stray 'OK', a
    leftover console prompt '>') gets ignored instead of misread as real
    speech."""
    if not raw_text:
        return ""
    marker = "SPEECH_MARKER:"
    idx = raw_text.find(marker)
    if idx == -1:
        return ""
    after_marker = raw_text[idx + len(marker):]
    value = after_marker.splitlines()[0] if after_marker else ""
    return value.strip('"').strip("'").strip()


def prime(arc):
    """Call once at startup - reads whatever's currently sitting in
    $SpeechPhrase (likely stale, leftover from before this script ran), so
    the first real new phrase spoken is correctly detected as new rather
    than the script reacting to old leftover text immediately. Prints the
    raw response so you can confirm ARC is actually responding to this
    variable at all."""
    raw = arc.send_and_receive('Print("SPEECH_MARKER:" + $SpeechPhrase)', timeout=1.0)
    print(f"  [debug] raw ARC response on startup: {raw!r}")
    _last_phrase[0] = _clean_response(raw)
    print(f"  [debug] starting baseline phrase: {_last_phrase[0]!r}")


def listen_for_command(arc):
    """Blocks until ARC's Speech Recognition skill reports a genuinely NEW
    phrase (different from the last one seen), then returns it cleaned up.
    Prints a heartbeat periodically so it's clear this is actively polling,
    not hung - and can be cancelled with Ctrl+C to fall back to typing."""
    poll_count = 0
    try:
        while True:
            raw = arc.send_and_receive('Print("SPEECH_MARKER:" + $SpeechPhrase)', timeout=SPEECH_POLL_INTERVAL)
            cleaned = _clean_response(raw)
            if cleaned and cleaned != _last_phrase[0]:
                _last_phrase[0] = cleaned
                return cleaned
            poll_count += 1
            if poll_count % 20 == 0:  # roughly every ~6 seconds at default poll interval
                print(f"  [debug] still listening... last raw response: {raw!r}")
            time.sleep(SPEECH_POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nSwitched to typing for this one.")
        return input("Command: ").strip()