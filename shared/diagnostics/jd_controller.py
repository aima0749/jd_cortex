"""
JD Controller - all-in-one, safe connect + execute
--------------------------------------------------------
Everything needed to safely connect to ARC and run a move, in one file:
  1. Connects to ARC with clear error handling (no silent failures)
  2. Sets safety limits on every mapped joint automatically on connect
  3. Validates move names before sending anything
  4. Confirms real completion via ARC's own status variable
  5. Simple interactive menu - just run the file and pick a move

Run:
    python jd_controller.py

Requires servo_map.py in the same folder.
"""

import socket
import time
from servo_map import SERVO_MAP, get_port

ARC_HOST = "127.0.0.1"
ARC_PORT = 6666
CONNECT_TIMEOUT = 5.0

# Friendly move name -> exact ARC Auto Position Action title.
# Update the right-hand values to match your ARC project exactly
# (right-click an action in ARC's Auto Position panel to see its real title).
MOVES = {
    "wave_hello":   "Hands Dance",
    "bow":          "Bow",
    "dance":        "Disco Dance",
    "fly":          "Fly",
    "get_up":       "Getup",
    "grab":         "Grab",
}

# Moves built from scratch as raw servo sequences (not prebuilt ARC Auto
# Position actions) - handled separately from MOVES since they call their
# own method instead of ControlCommand("Auto Position", ...).
RAW_MOVES = {
    "act_like_dog": "execute_dog_crouch",
}

# Conservative safety limits per joint (+/-30 from neutral 90, tighter
# +/-20 on legs since balance is higher-risk). Widen ONLY after manually
# verifying real safe range for that specific joint in ARC's Configure/
# Fine Tune Servo Profile tool.
SAFETY_LIMITS = {
    "D1":  (70, 150),   # neck
    "D2":  (60, 120),   # right shoulder
    "D3":  (60, 120),   # left shoulder
    "D7":  (60, 120),   # right upper arm
    "D4":  (60, 120),   # left upper arm
    "D8":  (60, 120),   # right lower arm
    "D5":  (60, 120),   # left lower arm
    "D9":  (30, 90),    # right hand/gripper
    "D6":  (30, 90),    # left hand/gripper
    "D16": (70, 110),   # right upper leg
    "D12": (70, 110),   # left upper leg
    "D17": (70, 110),   # right lower leg
    "D13": (70, 110),   # left lower leg
    "D18": (60, 120),   # right foot/ankle
    "D14": (60, 120),   # left foot/ankle
}


class JDController:
    def __init__(self):
        self.sock = None

    def connect(self):
        print(f"Connecting to ARC at {ARC_HOST}:{ARC_PORT}...")
        try:
            self.sock = socket.create_connection((ARC_HOST, ARC_PORT), timeout=CONNECT_TIMEOUT)
        except OSError as e:
            print(f"FAILED to connect: {e}")
            print("Check: is ARC open, project loaded, and the real robot connected?")
            return False
        print("Connected.\n")
        return True

    def disconnect(self):
        if self.sock:
            self.sock.close()
            self.sock = None
            print("Disconnected.")

    def _send(self, command_text):
        self.sock.sendall((command_text.strip() + "\n").encode("utf-8"))

    def _receive(self, timeout=2.0):
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(4096).decode("utf-8", errors="ignore").strip()
        except socket.timeout:
            return ""
        finally:
            self.sock.settimeout(None)

    def apply_safety_limits(self):
        print("Applying safety limits to all mapped joints...")
        for port, (min_pos, max_pos) in SAFETY_LIMITS.items():
            try:
                self._send(f"Servo.setMinPositionLimit({port}, {min_pos})")
                self._send(f"Servo.setMaxPositionLimit({port}, {max_pos})")
            except (BrokenPipeError, OSError) as e:
                print(f"  ERROR setting limits on {port}: {e}")
                continue
            print(f"  {port}: {min_pos}-{max_pos}")
        print("Safety limits applied.\n")

    def _wait_for_completion(self, max_wait=8.0, poll_interval=0.3):
        elapsed = 0.0
        while elapsed < max_wait:
            self._send('Print($AutoPositionStatus)')
            response = self._receive(timeout=poll_interval)
            if response and ("0" in response or "False" in response):
                return True
            time.sleep(poll_interval)
            elapsed += poll_interval
        print(f"  WARNING: no completion confirmation within {max_wait}s")
        return False

    def return_to_neutral(self):
        """Sends every mapped joint back to 90 (confirmed neutral position
        for all servos), gradually rather than snapping instantly - avoids
        the jerky all-joints-at-once motion flagged during initial testing."""
        print("Returning to neutral (all joints -> 90, gradual)...")
        current_targets = {port: 90 for port in SERVO_MAP}
        self._move_gradual(current_targets, steps=10, step_delay=0.08)
        print("At neutral.\n")

    def _move_gradual(self, target_positions, steps=10, step_delay=0.08):
        """Moves every given port toward its target angle in small
        increments rather than one instant jump, so multi-joint moves
        (like return-to-neutral, or the dog crouch below) look smooth
        instead of abrupt. target_positions: dict of port -> target angle.
        NOTE: assumes current position is 90 (neutral) as the start point,
        since ARC's TCP interface doesn't have an easy "read current servo
        angle" call wired up here yet - fine for moves that always start
        from neutral (which is every move in this controller, since
        return_to_neutral runs after each one)."""
        start_positions = {port: 90 for port in target_positions}
        for step in range(1, steps + 1):
            fraction = step / steps
            for port, target in target_positions.items():
                start = start_positions[port]
                interpolated = round(start + (target - start) * fraction)
                try:
                    self._send(f"Servo({port}, {interpolated})")
                except (BrokenPipeError, OSError) as e:
                    print(f"  ERROR moving {port}: {e}")
            time.sleep(step_delay)

    def execute_dog_crouch(self):
        """Raw servo sequence for an all-fours dog-crouch pose - built from
        scratch since no prebuilt ARC Auto Position action exists for this.
        Arms extend forward/down to act as 'front legs', torso lowers via
        bent legs, head tilts down. All target angles stay within
        SAFETY_LIMITS. UNVERIFIED ON REAL HARDWARE - test in small steps,
        watch closely, ideally with someone spotting the robot in case a
        joint direction assumption is wrong for your specific build."""
        print("Executing: act_like_dog (raw dog-crouch pose, built from scratch)")

        dog_crouch_targets = {
            "D1": 115,   # neck - tilt head down (toward upper safety bound)
            "D2": 100,   # right shoulder - slight forward
            "D3": 100,   # left shoulder - slight forward
            "D7": 115,   # right upper arm - extend forward/down like a front leg
            "D4": 115,   # left upper arm - extend forward/down like a front leg
            "D8": 110,   # right lower arm - slight bend, weight-bearing
            "D5": 110,   # left lower arm - slight bend, weight-bearing
            "D16": 100,  # right upper leg - bend to lower hips
            "D12": 100,  # left upper leg - bend to lower hips
            "D17": 100,  # right lower leg - bend to lower hips
            "D13": 100,  # left lower leg - bend to lower hips
            "D18": 105,  # right ankle - compensate for leg bend
            "D14": 105,  # left ankle - compensate for leg bend
        }

        self._move_gradual(dog_crouch_targets, steps=15, step_delay=0.1)
        print("  Dog-crouch pose reached (unverified - confirm visually).")

        self.return_to_neutral()
        return True

    def execute_move(self, move_name, max_wait=8.0):
        if move_name not in MOVES:
            print(f"REJECTED: '{move_name}' is not known. Options: {list(MOVES.keys())}")
            return False

        action_title = MOVES[move_name]
        print(f"Executing: {move_name} -> '{action_title}'")
        try:
            self._send(f'ControlCommand("Auto Position", AutoPositionAction, "{action_title}")')
        except (BrokenPipeError, OSError) as e:
            print(f"CONNECTION ERROR: {e}")
            return False

        completed = self._wait_for_completion(max_wait)
        if completed:
            print(f"  Confirmed complete: {move_name}")

        # always return to a known, safe starting state before the next move
        self.return_to_neutral()

        return completed


def interactive_menu(jd):
    move_names = list(MOVES.keys()) + list(RAW_MOVES.keys())
    while True:
        print("Available moves:")
        for i, name in enumerate(move_names, 1):
            tag = " (raw, built from scratch - unverified)" if name in RAW_MOVES else ""
            print(f"  {i}. {name}{tag}")
        print("  0. Quit")

        choice = input("\nPick a move number: ").strip()
        if choice == "0":
            break
        try:
            index = int(choice) - 1
            move_name = move_names[index]
        except (ValueError, IndexError):
            print("Invalid choice, try again.\n")
            continue

        confirm = input(f"Confirm run '{move_name}'? Watch the robot. (y/n): ").strip().lower()
        if confirm == "y":
            if move_name in RAW_MOVES:
                method_name = RAW_MOVES[move_name]
                getattr(jd, method_name)()
            else:
                jd.execute_move(move_name)
        print()


if __name__ == "__main__":
    jd = JDController()
    if not jd.connect():
        raise SystemExit(1)

    jd.apply_safety_limits()

    print("Ready. Test moves one at a time, watching the robot closely.\n")
    interactive_menu(jd)

    jd.disconnect()