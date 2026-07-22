"""
Reads the vision pipeline's scene_state.json (written continuously by
01_full_pipeline.py) fresh each time, and turns it into a short,
plain-English summary to feed into Gemini's prompt.
"""

import json
import os
import time

# Anchored to THIS file's own folder, not whatever directory the script
# happened to be launched from - same class of bug we fixed in the vision
# pipeline itself earlier (relative paths depend on launch dir otherwise).
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCENE_STATE_PATH = os.path.join(_BASE_DIR, "..", "vision_pipeline", "scene_state.json")

MAX_AGE_SECONDS = 10  # if the file is older than this, treat it as stale


def get_scene_summary():
    """Returns a short natural-language description of what JD currently
    sees, or None if the vision pipeline isn't running / data is stale."""
    if not os.path.exists(SCENE_STATE_PATH):
        return None

    try:
        with open(SCENE_STATE_PATH, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    age = time.time() - data.get("timestamp", 0)
    if age > MAX_AGE_SECONDS:
        return None

    people = data.get("people", {})
    if not people:
        return "No one is currently visible."

    lines = []
    for person_id, info in people.items():
        name = info.get("name")
        label = name if name and name != "unknown" else person_id
        parts = [label]
        if info.get("posture"):
            parts.append(info["posture"])
        if info.get("holding"):
            parts.append(f"holding {info['holding']}")
        if info.get("sitting_on"):
            parts.append(f"sitting on {info['sitting_on']}")
        if info.get("gesture"):
            parts.append(info["gesture"])
        lines.append(" - ".join(parts))

    return "Currently visible: " + "; ".join(lines)