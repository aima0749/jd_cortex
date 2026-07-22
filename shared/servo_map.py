"""
JD Servo Map - CONFIRMED, straight from ARC's Avatar/Design panel
--------------------------------------------------------------------------
This is the real, official port mapping for this JD robot, read directly
from ARC's own "Avatar JD" design view - not guessed, not scanned, the
actual configuration ARC itself uses.

Every future script (Move Library, gestures, ARC bridge) should import
SERVO_MAP or use get_port() from here instead of hardcoding port numbers.
"""

SERVO_MAP = {
    "D1":  {"joint_name": "neck", "notes": "head tilt/turn"},

    "D2":  {"joint_name": "right_shoulder", "notes": ""},
    "D3":  {"joint_name": "left_shoulder", "notes": ""},

    "D7":  {"joint_name": "right_upper_arm", "notes": ""},
    "D4":  {"joint_name": "left_upper_arm", "notes": ""},

    "D8":  {"joint_name": "right_lower_arm", "notes": ""},
    "D5":  {"joint_name": "left_lower_arm", "notes": ""},

    "D9":  {"joint_name": "right_hand", "notes": ""},
    "D6":  {"joint_name": "left_hand", "notes": ""},

    "D16": {"joint_name": "right_upper_leg", "notes": ""},
    "D12": {"joint_name": "left_upper_leg", "notes": ""},

    "D17": {"joint_name": "right_lower_leg", "notes": ""},
    "D13": {"joint_name": "left_lower_leg", "notes": ""},

    "D18": {"joint_name": "right_foot", "notes": ""},
    "D14": {"joint_name": "left_foot", "notes": ""},
}

# All joints default to 90 = neutral/center position, based on the
# Avatar panel showing every field currently at 90.
DEFAULT_POSITION = 90


def get_port(joint_name):
    """Look up the port for a given joint name. Returns None if not found."""
    for port, info in SERVO_MAP.items():
        if info["joint_name"] == joint_name:
            return port
    return None


def get_joint(port):
    """Look up the joint name for a given port. Returns None if not found."""
    info = SERVO_MAP.get(port)
    return info["joint_name"] if info else None


if __name__ == "__main__":
    print("Confirmed JD servo map:")
    for port, info in sorted(SERVO_MAP.items()):
        print(f"  {port}: {info['joint_name']}")