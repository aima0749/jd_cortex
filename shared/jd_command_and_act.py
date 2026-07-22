"""
JD Command & Act - the full working system
==================================================
This is the whole pipeline, assembled and working together:

  1. Connect to ARC (real, tested)
  2. Take a text command (typed or voice)
  3. Try instant local matching first (keyword/synonym/exact-name) - if it's
     clearly a literal action command, just do it, no Gemini call needed.
  4. Otherwise, ask Gemini for BOTH things at once:
       - a short, natural spoken reply (JD "answers intelligently")
       - an optional action match, ONLY if the request clearly maps to one
         of the real known actions (never invented)
  5. Speak the reply (if any) via JD's real onboard speaker (SayEZBWait,
     same TCP mechanism as the vision pipeline).
  6. Validate any action match against the real known-safe lists before
     ever sending it to the robot - Gemini's opinion alone is never enough.
  7. If a validated action was found, execute it, then return JD to a
     safe standing/neutral position.
  8. Ready for the next command.

Requires (same folder): known_actions.py

Run:
    python jd_command_and_act.py
"""

import os
import socket
import time
from known_actions import (
    MOVEMENTS, SOUNDS, LIGHTS,
    do_movement, do_sound, do_light, return_to_standing,
    describe_all_known,
)

ARC_HOST = "127.0.0.1"
ARC_PORT = 6666

# Get a free key at https://aistudio.google.com/apikey
# MUST be a real key - "PUT_YOUR_KEY_HERE" will fail every Gemini call
# with "API key not valid".

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PUT_YOUR_KEY_HERE")

# Mo  del name is centralized here since Google has been deprecating/
# restricting model names rapidly. GEMINI_MODEL_CANDIDATES is tried in
# order - if one gets 404'd (deprecated/restricted), the next one is
# tried automatically, so a future deprecation doesn't require editing
# code by hand again. Update this list if ALL of them ever start failing
# (run list_available_models() below to see what your key currently has).
GEMINI_MODEL_CANDIDATES = [
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]
GEMINI_TIMEOUT = 20.0   # seconds - generous, since occasional slow responses are normal
GEMINI_MAX_RETRIES = 2  # extra attempts on timeout/connection errors before giving up


def list_available_models():
    """One-off diagnostic: asks Google directly which models your key can
    actually use right now, instead of guessing model names one by one.
    Run with: python -c "from jd_command_and_act import list_available_models; list_available_models()" """
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if not response.ok:
            print(f"ListModels failed: HTTP {response.status_code}\n{response.text}")
            return
        data = response.json()
        for model in data.get("models", []):
            name = model.get("name", "")
            methods = model.get("supportedGenerationMethods", [])
            if "generateContent" in methods:
                print(name)
    except Exception as e:
        print(f"ListModels failed: {e}")

# ---------------------------------------------------------------------------
# LOCAL EXACT-NAME MATCHING - instant, free, no API. Only catches the case
# where someone says a real action's exact name directly (e.g. "do the
# Headstand"). Deliberately NOT a big hardcoded synonym dictionary anymore -
# that used to intercept phrases before Gemini ever saw them, making the
# system feel rigid/pre-scripted instead of actually understanding what was
# said. Now, anything that isn't a literal exact name goes to Gemini, which
# has full freedom to interpret intent and pick the closest reasonable
# action (see gemini_understand's prompt) - genuinely smarter, at the small
# cost of a network call for anything non-literal.
# ---------------------------------------------------------------------------


def local_match(text):
    text_lower = text.lower()

    # Does the text directly contain a real action's exact name? Covers
    # every movement/light/sound without needing to hardcode phrasing for
    # each one - if it's not a literal name, it falls through to Gemini.
    for movement in MOVEMENTS:
        if movement.lower() in text_lower:
            return ("movement", movement)
    for light in LIGHTS:
        if light.lower() in text_lower:
            return ("light", light)
    for track_num, filename in SOUNDS.items():
        song_name = filename.replace(".mp3", "").lower()
        if song_name in text_lower:
            return ("sound", track_num)

    return None


def _call_gemini_once(model_name, prompt):
    """Single attempt at one model. Returns (result_text, error_kind) where
    error_kind is None (success), 'not_found' (try next model), or
    'other' (network/timeout/etc - worth retrying same model)."""
    import requests
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, json=payload, timeout=GEMINI_TIMEOUT)
    except requests.exceptions.RequestException as e:
        print(f"  [Gemini] network error on {model_name}: {e}")
        return None, "other"

    if response.status_code == 404:
        print(f"  [Gemini] {model_name} unavailable (404) - trying next model...")
        return None, "not_found"
    if not response.ok:
        print(f"  [Gemini] HTTP {response.status_code} on {model_name}: {response.text}")
        return None, "other"

    try:
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip(), None
    except (KeyError, IndexError, ValueError) as e:
        print(f"  [Gemini] couldn't parse response from {model_name}: {e}")
        return None, "other"


def call_gemini(prompt):
    """Tries each model in GEMINI_MODEL_CANDIDATES in order (skipping ones
    that 404 as deprecated/restricted), retrying each one a couple times
    on transient network/timeout errors before moving on. Returns the raw
    response text, or None if every model/attempt failed."""
    for model_name in GEMINI_MODEL_CANDIDATES:
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            result_text, error_kind = _call_gemini_once(model_name, prompt)
            if error_kind is None:
                return result_text
            if error_kind == "not_found":
                break  # no point retrying a model that doesn't exist - move to next model
            print(f"  [Gemini] retrying {model_name} (attempt {attempt}/{GEMINI_MAX_RETRIES})...")
            time.sleep(1.5)  # brief pause before retrying - don't hammer a broken connection instantly
    return None


def gemini_understand(text):
    """
    Single Gemini call that returns BOTH:
      - a short natural spoken reply (JD 'answering intelligently')
      - an optional action match, ONLY if the request clearly maps to a
        real known action - never invented, always re-validated afterward.

    Returns (reply_text_or_None, (category, name)_or_None).
    """
    prompt = f"""You are JD, a friendly robot. A person just said to you: "{text}"

{describe_all_known()}

Respond in EXACTLY this two-line format, nothing else:
REPLY: <a short, natural, spoken-style reply from JD, 1-2 sentences>
MATCH: <category>|<name>

For the MATCH line: pick the CLOSEST real action from the lists above that
reasonably represents what the person asked for - it does not need to be a
literal name match. For example, someone asking JD to act like a bee,
bird, or something else that flies could reasonably match "Fly"; acting
like a dog or monkey could reasonably match "Gorilla" if that's the
closest option available. Use your judgment for creative or descriptive
requests, but only pick something if there's a genuinely reasonable
connection - don't force a match onto something unrelated.

If nothing on the list reasonably fits, put exactly:
MATCH: NONE

Never invent an action name that isn't on the list above - only ever pick
from the real categories and names given."""

    result_text = call_gemini(prompt)

    if result_text is None:
        # Every model/attempt failed - still give a graceful spoken fallback
        # instead of going completely silent, so JD never looks "broken"
        # to whoever's watching.
        return "Sorry, I'm having trouble thinking right now. Try again in a moment.", None

    reply = None
    action = None
    for line in result_text.splitlines():
        line = line.strip()
        if line.startswith("REPLY:"):
            reply = line[len("REPLY:"):].strip()
        elif line.startswith("MATCH:"):
            match_val = line[len("MATCH:"):].strip()
            if match_val and match_val != "NONE":
                try:
                    category, name = match_val.split("|", 1)
                    name = name.strip()
                    category = category.strip()
                    if category == "sound":
                        name = int(name)
                    action = (category, name)
                except (ValueError, IndexError):
                    action = None

    return reply, action


def validate(category, name):
    """Final safety check - even a Gemini match gets re-checked against
    the real list before anything is sent to the robot."""
    if category == "movement":
        return name in MOVEMENTS
    if category == "sound":
        return name in SOUNDS
    if category == "light":
        return name in LIGHTS
    return False


def execute(sock, category, name):
    if category == "movement":
        return do_movement(sock, name)
    if category == "sound":
        return do_sound(sock, name)
    if category == "light":
        return do_light(sock, name)
    return False


def _escape_for_ezscript(text):
    """EZ-Script strings use double quotes - escape any that appear in text."""
    return text.replace('"', "'")


def speak(sock, text):
    """Speaks a line via JD's real onboard speaker, using the same
    SayEZBWait TCP mechanism proven in the vision pipeline. Blocking -
    waits for ARC's reply so we don't fire the next command mid-speech."""
    if not text:
        return
    safe_text = _escape_for_ezscript(text)
    command = f'SayEZBWait("{safe_text}")\n'
    try:
        sock.sendall(command.encode("utf-8"))
        sock.settimeout(20.0)
        try:
            sock.recv(4096)
        except socket.timeout:
            print("  [TTS] no response from ARC within timeout (may still be speaking)")
        finally:
            sock.settimeout(None)
    except (BrokenPipeError, OSError) as e:
        print(f"  [TTS ERROR] Failed to speak: {e}")


def run_action(sock, category, name):
    """Executes a validated action, then returns JD to standing if it
    was a movement."""
    success = execute(sock, category, name)
    if success and category == "movement":
        time.sleep(2.5)  # let the movement play out before resetting
        print("  Returning to standing...")
        return_to_standing(sock)
        time.sleep(1.5)
    return success


def process_command(sock, text):
    print(f"\n>> Command: \"{text}\"")

    # 1. Instant local match first - covers literal, unambiguous action
    #    commands ("sit down", "dance") without spending a Gemini call.
    local_result = local_match(text)
    if local_result:
        category, name = local_result
        print(f"  Matched (local): {category} -> {name}")
        if validate(category, name):
            run_action(sock, category, name)
        else:
            print(f"  REJECTED at validation - '{name}' not confirmed safe. Nothing sent.")
        print("  Done.\n")
        return

    # 2. No literal action match - ask Gemini for an intelligent reply,
    #    AND (only if it clearly maps to a real action) let it act too.
    #    These are independent: JD can answer conversationally even when
    #    nothing physical happens, and it only ever acts on a validated match.
    reply, action = gemini_understand(text)

    if reply:
        print(f"  JD says: {reply}")
        speak(sock, reply)
    else:
        print("  (no spoken reply generated)")

    if action:
        category, name = action
        if validate(category, name):
            print(f"  Also executing matched action: {category} -> {name}")
            run_action(sock, category, name)
        else:
            print(f"  Gemini suggested '{name}' but it's not on the safe list - ignoring, nothing sent.")

    print("  Done.\n")


def _send(sock, command_text):
    sock.sendall((command_text.strip() + "\n").encode("utf-8"))


def _receive(sock, timeout=1.0):
    sock.settimeout(timeout)
    try:
        return sock.recv(4096).decode("utf-8", errors="ignore").strip()
    except socket.timeout:
        return ""
    finally:
        sock.settimeout(None)


_last_speech_phrase = [None]  # tracks last seen $SpeechPhrase value across polls


def get_arc_speech_phrase(sock, poll_interval=0.3):
    """Polls ARC's Speech Recognition skill's $SpeechPhrase variable over
    the same TCP connection used for everything else - this is the raw
    text ARC just heard, NOT limited to a hardcoded phrase list, so any
    natural sentence spoken gets picked up. Blocks until a genuinely NEW
    phrase appears (different from the last one seen)."""
    while True:
        _send(sock, "Print($SpeechPhrase)")
        response = _receive(sock, timeout=poll_interval)
        if response and response != _last_speech_phrase[0]:
            _last_speech_phrase[0] = response
            return response
        time.sleep(poll_interval)


def get_text_input(mode, sock=None):
    if mode == "type":
        return input("Command: ").strip()

    if mode == "arc":
        print("Listening via ARC Speech Recognition skill...")
        return get_arc_speech_phrase(sock)

    # mode == "mic" - Python SpeechRecognition + local microphone
    import speech_recognition as sr
    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            print("Listening... (press Ctrl+C to switch back to typing)")
            try:
                audio = recognizer.listen(source, timeout=6, phrase_time_limit=6)
            except sr.WaitTimeoutError:
                return ""
    except KeyboardInterrupt:
        print("\nSwitched to typing for this one.")
        return input("Command: ").strip()

    try:
        return recognizer.recognize_google(audio)
    except (sr.UnknownValueError, sr.RequestError) as e:
        print(f"Didn't catch that ({e}).")
        return ""
    
    except (ConnectionResetError, ConnectionError, OSError) as e:
        print(f"Network hiccup talking to speech service ({e}). Try again.")
        return ""


def main():
    print(f"Connecting to ARC at {ARC_HOST}:{ARC_PORT}...")
    try:
        sock = socket.create_connection((ARC_HOST, ARC_PORT), timeout=5)
    except OSError as e:
        print(f"FAILED to connect: {e}")
        return
    print("Connected.\n")

    if GEMINI_API_KEY == "PUT_YOUR_KEY_HERE":
        print("WARNING: GEMINI_API_KEY is still the placeholder - conversational")
        print("replies and Gemini-based action matching will fail until you set")
        print("a real key from https://aistudio.google.com/apikey\n")

    use_voice = input("Input mode - (t)ype, (m)ic, or (a)rc speech skill? [t/m/a]: ").strip().lower()
    if use_voice == "a":
        mode = "arc"
        # Seed the last-seen phrase with whatever's currently sitting in
        # $SpeechPhrase from before this script started, so we only react
        # to genuinely NEW speech going forward, not stale leftover text.
        _send(sock, "Print($SpeechPhrase)")
        _last_speech_phrase[0] = _receive(sock, timeout=1.0)
        print("Voice mode (ARC Speech Recognition skill). Speak your command each time.\n")
    elif use_voice == "m":
        mode = "mic"
        print("Voice mode (local microphone). Speak your command each time.\n")
    else:
        mode = "type"
        print("Type a command (or 'quit' to exit).\n")

    while True:
        text = get_text_input(mode, sock)
        if not text:
            continue
        if text.lower() == "quit":
            break
        process_command(sock, text)

    sock.close()
    print("Disconnected.")


if __name__ == "__main__":
    main()