import time

import config
import gemini_brain
import voice_parakeet
import tts
import conversation_memory
from arc_connection import ARCConnection
from known_actions import (
    MOVEMENTS, SOUNDS, LIGHTS,
    do_movement, do_sound, do_light, return_to_standing,
    describe_all_known,
)

try:
    import scene_context
    HAS_SCENE_CONTEXT = True
except ImportError:
    HAS_SCENE_CONTEXT = False
    print("(scene_context.py not found - running without vision context)\n")

FORGET_PHRASES = ["forget this conversation", "forget everything", "clear your memory", "start fresh"]


def get_scene_summary_safe():
    if not HAS_SCENE_CONTEXT:
        return None
    try:
        return scene_context.get_scene_summary()
    except Exception as e:
        print(f"  [scene_context] failed to get summary: {e}")
        return None


def local_match(text):
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
        time.sleep(2.5)
        print("  Returning to standing...")
        return_to_standing(arc.sock)
        time.sleep(1.5)
    return success


def speak_debug(arc, text):
    print("  [DEBUG] Calling tts.speak() now...")
    tts.speak(arc, text)
    print("  [DEBUG] tts.speak() call finished.")


def process_command(arc, text):
    print(f"\n>> Command: \"{text}\"")

    text_lower = text.lower()
    if any(phrase in text_lower for phrase in FORGET_PHRASES):
        conversation_memory.clear()
        spoken_line = "Okay, I've cleared what I remember. Starting fresh!"
        print(f"  JD says: {spoken_line}")
        speak_debug(arc, spoken_line)
        print("  Done.\n")
        return

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
    history_block = conversation_memory.get_history_block()
    reply, action = gemini_brain.understand(text, describe_all_known, scene_summary, history_block)

    if reply:
        print(f"  JD says: {reply}")
        speak_debug(arc, reply)
        conversation_memory.add_turn(text, reply)
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