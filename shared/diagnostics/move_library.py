"""
JD Move Library - CORRECTED
--------------------------------
Uses ARC's own prebuilt, tested Auto Position ACTIONS (visible in your
Auto Position panel's Actions list: Bow, Disco Dance, Fly, Getup,
Gorilla, Grab, Hands Dance) instead of inventing raw servo angles.

CONFIRMED correct syntax (from Synthiam's own docs + community examples):
    ControlCommand("Auto Position", AutoPositionAction, "Bow")

Note: earlier attempts used AutoPositionFrame, which is for individual
POSES, not named ACTION sequences - that's why "Bow" failed before.
AutoPositionAction is the correct parameter for these.

Usage:
    from move_library import MOVES, execute_move
    execute_move(sock, "wave_hello")
"""

import socket
import time

ARC_HOST = "127.0.0.1"
ARC_PORT = 6666

# Map friendly names (what your code/Gemini will reference) to the
# EXACT action titles as they appear in ARC's Auto Position Actions list.
# Update the right-hand values if your actual action names differ.
MOVES = {
    "wave_hello":  "Hands Dance",   # adjust to your real "wave" action name if different
    "bow":         "Bow",
    "dance":       "Disco Dance",
    "fly":         "Fly",
    "get_up":      "Getup",
    "act_like_dog": "Gorilla",      # closest existing action to "dog-like" - reuse until a
                                       # real dog_pose action is built
    "grab":        "Grab",
}


def send_command(sock, command_text):
    full_command = command_text.strip() + "\n"
    sock.sendall(full_command.encode("utf-8"))


def set_safety_limits(sock):
    """
    Sets min/max position limits per joint BEFORE any move is attempted.
    Once set, ARC will refuse to send that servo past these angles no
    matter what a move/action tries to do - this is the actual safety
    net, not just careful move design.

    CONSERVATIVE STARTING VALUES (60-120, i.e. +/-30 from neutral 90) -
    the same cautious range used in the raw move library earlier. Widen
    these ONLY after manually testing that specific joint's real safe
    range in ARC's Avatar/Design panel and confirming no strain.

    The neck/gripper/ankle values marked CONFIRMED come directly from
    Synthiam's own official JD example project - real, but possibly
    specific to that example robot's calibration, not guaranteed
    identical to yours. Verify before fully trusting even these.
    """
    limits = {
        # CONFIRMED (from Synthiam's official JD init script example) -
        # still worth spot-checking on your own robot before relying on
        "D1":  (70, 150),   # neck - only min was confirmed, max is a guess, VERIFY
        "D6":  (30, 90),    # left gripper - CONFIRMED
        "D9":  (30, 90),    # right gripper - CONFIRMED
        "D14": (60, 120),   # left ankle - CONFIRMED
        "D18": (60, 120),   # right ankle - CONFIRMED

        # UNVERIFIED conservative defaults - widen only after manual
        # testing each one individually in the Avatar/Design panel
        "D2":  (60, 120),   # right shoulder
        "D3":  (60, 120),   # left shoulder
        "D7":  (60, 120),   # right upper arm
        "D4":  (60, 120),   # left upper arm
        "D8":  (60, 120),   # right lower arm
        "D5":  (60, 120),   # left lower arm
        "D16": (70, 110),   # right upper leg - tighter range, balance-sensitive
        "D12": (70, 110),   # left upper leg
        "D17": (70, 110),   # right lower leg
        "D13": (70, 110),   # left lower leg
    }

    print("Setting safety limits on all mapped joints...")
    for port, (min_pos, max_pos) in limits.items():
        send_command(sock, f"Servo.setMinPositionLimit({port}, {min_pos})")
        send_command(sock, f"Servo.setMaxPositionLimit({port}, {max_pos})")
        print(f"  {port}: limited to {min_pos}-{max_pos}")
    print("Safety limits set.\n")


def execute_move(sock, move_name, wait_seconds=3.0):
    """Triggers a real ARC Auto Position Action by its mapped name."""
    if move_name not in MOVES:
        print(f"Unknown move: {move_name}")
        return

    action_title = MOVES[move_name]
    command = f'ControlCommand("Auto Position", AutoPositionAction, "{action_title}")'
    print(f"Executing move: {move_name} -> ARC action: '{action_title}'")
    send_command(sock, command)
    time.sleep(wait_seconds)  # crude wait - see note below on a better approach


if __name__ == "__main__":
    print(f"Connecting to ARC at {ARC_HOST}:{ARC_PORT}...")
    sock = socket.create_connection((ARC_HOST, ARC_PORT), timeout=5)
    print("Connected.\n")

    set_safety_limits(sock)

    print("Testing moves ONE AT A TIME. Watch the robot closely.")
    print("Keep a hand near the power switch, especially for Fly/Getup.\n")

    for move_name in MOVES:
        input(f"Press Enter to test '{move_name}' (or Ctrl+C to stop)...")
        execute_move(sock, move_name)
        print(f"Done with {move_name}. Check the robot before continuing.\n")

    sock.close()
    print("\nAll moves tested.")