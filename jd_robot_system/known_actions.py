"""
Known Actions Registry - the ONLY things JD can be told to do
--------------------------------------------------------------------------
Every real, confirmed action, sound, and light effect JD has, taken
directly from your ARC project - nothing invented. This is the single
list the intent matcher (local + Gemini) is allowed to choose from.

Confirmed ControlCommand syntax per category (from Synthiam's own docs):
  Movement: ControlCommand("Auto Position", AutoPositionAction, "Bow")
  Sound:    ControlCommand("Soundboard v4", Track_0)   <- bareword Track_N, not filename
  Light:    ControlCommand("RGB Animator", AutoPositionAction, "Spin")
  Reset:    ControlCommand("Auto Position", "AutoPositionFrameJump", "Standing")
"""

# --- MOVEMENTS: real titles from your Auto Position Actions list ---
# Verify each exact title in ARC (right-click -> check title) if any
# fail with "Cannot find Action with Title" errors, same issue "Bow" had before.
MOVEMENTS = [
    "Bow", "Disco Dance", "Fly", "Getup", "Gorilla", "Grab", "Hands Dance",
    "Happy Hands", "Head Bob", "Head Bob Feet", "Headstand", "Jump Jack",
    "Kick", "Lunge Singing", "Pass the Mic", "Point", "Predance", "Pushups",
    "Roll Hands", "Shimmy", "Singing", "Singing Hands In", "Singing with Hands",
    "Sit Down", "Sit Wave", "Situps", "Splits", "Stand From Sit"
    , "Thinking", "Throw Mic", "Wave", "YMCA Dance", "YMCA March",
]

# --- SOUNDS: real tracks from your Soundboard v4, by track number ---
SOUNDS = {
    0: "You Haunt Me.mp3",
    1: "Fly Like An Eagle.mp3",
    2: "Lose Yourself To Dance.mp3",
    3: "Camera Click.mp3",
    4: "Buddy.mp3",
    5: "Dubstep.mp3",
    6: "House.mp3",
    7: "Pop.mp3",
    8: "Ukulele.mp3",
    9: "Happy Birthday.mp3",
}

# --- LIGHTS: real actions from your RGB Animator ---
LIGHTS = [
    "Banana", "Big-Small", "Diag Scan", "Disco", "Dots", "Expressions",
    "Flash", "Scanner", "Spin", "Spin Roll", "Stripes", "Test", "Wink",
]


def send_command(sock, command_text):
    sock.sendall((command_text.strip() + "\n").encode("utf-8"))


def do_movement(sock, title):
    if title not in MOVEMENTS:
        print(f"REJECTED: '{title}' is not a known movement.")
        return False
    send_command(sock, f'ControlCommand("Auto Position", AutoPositionAction, "{title}")')
    return True


def do_sound(sock, track_number):
    if track_number not in SOUNDS:
        print(f"REJECTED: track {track_number} is not known.")
        return False
    send_command(sock, f'ControlCommand("Soundboard v4", Track_{track_number})')
    return True


def do_light(sock, title):
    if title not in LIGHTS:
        print(f"REJECTED: '{title}' is not a known light effect.")
        return False
    send_command(sock, f'ControlCommand("RGB Animator", AutoPositionAction, "{title}")')
    return True


def return_to_standing(sock):
    send_command(sock, 'ControlCommand("Auto Position", "AutoPositionFrameJump", "Standing")')


def describe_all_known():
    """Human-readable summary of everything JD can do - useful for
    building the Gemini prompt later."""
    lines = ["Movements JD can perform:"]
    lines += [f"  - {m}" for m in MOVEMENTS]
    lines.append("\nSounds JD can play:")
    lines += [f"  - Track {n}: {name}" for n, name in SOUNDS.items()]
    lines.append("\nLight effects JD can display:")
    lines += [f"  - {l}" for l in LIGHTS]
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe_all_known())