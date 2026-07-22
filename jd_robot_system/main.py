"""
JD Command & Act - main entry point.

Flow per command:
  1. Get text - typed, or spoken via local Parakeet (voice_parakeet.py),
     using whatever mic Windows has set as default (laptop or headphone).
  2. Check for an exact literal action name match first (instant, free,
     no Gemini call needed).
  3. Otherwise, ask Gemini for a spoken reply AND an optional action
     match, with scene context if available - Gemini can use judgment
     for creative phrasing, but can never invent an action name.
  4. Speak the reply via JD's onboard speaker.
  5. If an action was matched, validate it against the real known-safe
     lists (MOVEMENTS/SOUNDS/LIGHTS from known_actions.py) before ever
     sending anything to the robot - Gemini's opinion alone is never
     enough.
  6. Execute the validated action, then return JD to standing/neutral.

Requires (same folder): known_actions.py, config.py, gemini_brain.py,
voice_parakeet.py, tts.py, arc_connection.py. scene_context.py is
optional - if missing, JD just runs without vision-based context.

DEBUG PRINTS: this version has extra [DEBUG] lines around both the
action-execution path and the TTS/speak path, added specifically to
figure out why SayEZBWait sometimes produces no audible sound even
though ARC responds without error. Once TTS is confirmed working
reliably, these can be removed or commented out.

Run:
    python main.py
"""
import time

import config
import gemini_brain
import voice_parakeet
import tts
from arc_connection import ARCConnection
from known_actions import (
    MOVEMENTS, SOUNDS, LIGHTS,
    do_movement, do_sound, do_light, return_to_standing,
    describe_all_known,
)

# scene_context is optional - don't crash the whole system if it's not
# built yet or not present in this folder.
try:
    import scene_context
    HAS_SCENE_CONTEXT = True
except ImportError:
    HAS_SCENE_CONTEXT = False
    print("(scene_context.py not found - running without vision context)\n")


def get_scene_summary_safe():
    if not HAS_SCENE_CONTEXT:
        return None
    try:
        return scene_context.get_scene_summary()
    except Exception as e:
        print(f"  [scene_context] failed to get summary: {e}")
        return None


def local_match(text):
    """Instant, free match against a real action's exact name - no Gemini
    call needed for literal commands like 'do the Headstand'."""
    text_lower = text.lower()
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


def validate(category, name):
    """Final safety check - even a Gemini match gets re-checked against
    the real list before anything is sent to the robot. Case-insensitive
    on the name so a trivial casing difference from Gemini doesn't wrongly
    reject an otherwise-real match."""
    if category == "movement":
        return next((m for m in MOVEMENTS if m.lower() == str(name).lower()), None)
    if category == "sound":
        return name if name in SOUNDS else None
    if category == "light":
        return next((l for l in LIGHTS if l.lower() == str(name).lower()), None)
    return None


def execute(arc, category, name):
    print(f"  [DEBUG] Attempting to execute: {category} -> {name}")
    if category == "movement":
        result = do_movement(arc.sock, name)
        print(f"  [DEBUG] do_movement returned: {result}")
        return result
    if category == "sound":
        result = do_sound(arc.sock, name)
        print(f"  [DEBUG] do_sound returned: {result}")
        return result
    if category == "light":
        result = do_light(arc.sock, name)
        print(f"  [DEBUG] do_light returned: {result}")
        return result
    return False


def run_action(arc, category, name):
    success = execute(arc, category, name)
    if success and category == "movement":
        time.sleep(2.5)  # let the movement play out before resetting
        print("  Returning to standing...")
        return_to_standing(arc.sock)
        time.sleep(1.5)
    return success


def speak_debug(arc, text):
    """Wraps tts.speak() with debug prints so we can see whether the call
    is reached, and whether it completes, times out, or errors - since
    tts.speak() itself stays silent on a 'successful but no real audio'
    response from ARC."""
    print("  [DEBUG] Calling tts.speak() now...")
    tts.speak(arc, text)
    print("  [DEBUG] tts.speak() call finished.")


def process_command(arc, text):
    print(f"\n>> Command: \"{text}\"")

    local_result = local_match(text)
    if local_result:
        category, name = local_result
        print(f"  Matched (local): {category} -> {name}")
        if validate(category, name):
            spoken_line = f"Okay, {name}"
            print(f"  JD says: {spoken_line}")
            speak_debug(arc, spoken_line)
            run_action(arc, category, name)
        else:
            print(f"  REJECTED at validation - '{name}' not confirmed safe. Nothing sent.")
        print("  Done.\n")
        return

    scene_summary = get_scene_summary_safe()
    reply, action = gemini_brain.understand(text, describe_all_known, scene_summary)

    if reply:
        print(f"  JD says: {reply}")
        speak_debug(arc, reply)
    else:
        print("  (no spoken reply generated)")

    if action:
        category, name = action
        matched_name = validate(category, name)
        if matched_name:
            print(f"  Also executing matched action: {category} -> {matched_name}")
            run_action(arc, category, matched_name)
        else:
            print(f"  Gemini suggested '{name}' but it's not on the safe list - ignoring, nothing sent.")

    print("  Done.\n")


def main():
    arc = ARCConnection()
    if not arc.connect():
        return

    if config.GEMINI_API_KEY == "PUT_YOUR_KEY_HERE":
        print("WARNING: GEMINI_API_KEY is still the placeholder in config.py -")
        print("conversational replies and Gemini-based matching will fail until")
        print("you set a real key from https://aistudio.google.com/apikey\n")

    mode = input("Input mode - (t)ype or (v)oice via mic [local Parakeet]? [t/v]: ").strip().lower()
    if mode == "v":
        print("Voice mode (local Parakeet, laptop/headphone mic - whichever")
        print("Windows has set as default input device).")
        print("Speak your command each time.\n")
    else:
        mode = "t"
        print("Type a command (or 'quit' to exit).\n")

    while True:
        if mode == "v":
            text = voice_parakeet.listen_for_command()
            if text:
                print(f"  (heard: \"{text}\")")
        else:
            text = input("Command: ").strip()

        if not text:
            continue
        if text.lower() == "quit":
            break
        process_command(arc, text)

    arc.disconnect()


if __name__ == "__main__":
    main()