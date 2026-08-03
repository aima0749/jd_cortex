"""
Ambient Watcher
--------------------------
Runs standalone, alongside the vision pipeline, main.py, and
surveillance_watcher.py. Periodically compares the current
scene_state.json against what it looked like last check, and - only
when something genuinely changed - asks Gemini whether a natural,
occasional comment is warranted. Most of the time the answer is
nothing, on purpose, so JD doesn't narrate constantly like a sports
commentator.

This is SOCIAL/PROACTIVE, not safety-related (that's
surveillance_watcher.py's job). Unlike that file, this one genuinely
depends on Gemini/network - there's no meaningful offline version of
"is this worth commenting on". If Gemini/network is unavailable, this
just silently skips commenting that cycle - never blocks or breaks
anything else.

Does NOT open its own ARC connection - queues any comment via
speech_queue.py, same as surveillance_watcher.py, so only main.py ever
actually speaks.

Detects three kinds of change per tracked person:
  - ARRIVAL   - a person ID appears that wasn't present last check
  - CHANGE    - posture/holding/sitting_on changed since last check
  - IDLE      - same state held continuously for a long time
  - DEPARTURE - a person ID that was present is now gone

Run:
    python ambient_watcher.py
Stop:
    Ctrl+C
"""

import json
import os
import time

import gemini_brain
import speech_queue

try:
    import scene_context
    HAS_SCENE_CONTEXT = True
except ImportError:
    HAS_SCENE_CONTEXT = False

SCENE_STATE_PATH = "../vision_pipeline/scene_state.json"
POLL_INTERVAL = 5.0            # ambient, not urgent - check every 5 seconds
MAX_AGE_SECONDS = 10
IDLE_THRESHOLD_SECONDS = 300    # 5 minutes unchanged before an idle comment is considered
AMBIENT_MIN_GAP_SECONDS = 45    # never comment more often than this, however many things change

_last_comment_time = [0.0]
_previous_people = {}    # person_id -> {"name", "posture", "holding", "sitting_on"}
_state_since = {}        # person_id -> timestamp when their current state started
_idle_commented = set()  # person_ids already given an idle comment for their current streak


def _get_scene_summary_safe():
    if not HAS_SCENE_CONTEXT:
        return None
    try:
        return scene_context.get_scene_summary()
    except Exception:
        return None


def read_scene_state():
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
    return data


def _state_key(info):
    return (info.get("posture"), info.get("holding"), info.get("sitting_on"))


def _maybe_comment(event_description):
    """Rate-limited across ALL ambient comments - asks Gemini, speaks
    only if it returns something and enough time has passed since the
    last comment."""
    if time.time() - _last_comment_time[0] < AMBIENT_MIN_GAP_SECONDS:
        return

    scene_summary = _get_scene_summary_safe()
    comment = gemini_brain.ambient_comment(event_description, scene_summary)

    if comment:
        print(f"  [ambient] {event_description} -> \"{comment}\"")
        speech_queue.request_speech(comment)
        _last_comment_time[0] = time.time()
    else:
        print(f"  [ambient] {event_description} -> (no comment)")


def check_for_changes(scene_data):
    people = scene_data.get("people", {})
    now = time.time()

    for person_id, info in people.items():
        name = info.get("name", "unknown")
        display = name if name != "unknown" else f"person {person_id}"
        key = _state_key(info)

        if person_id not in _previous_people:
            # New track ID this session - could be a genuine new arrival,
            # or the tracker reassigning an ID for someone already here
            # (known limitation without a smarter re-identification step).
            _maybe_comment(f"{display} just appeared in view.")
            _state_since[person_id] = now
            _idle_commented.discard(person_id)
        else:
            prev_key = _state_key(_previous_people[person_id])
            if key != prev_key:
                _maybe_comment(f"{display}'s situation changed: now {info}.")
                _state_since[person_id] = now
                _idle_commented.discard(person_id)
            else:
                idle_duration = now - _state_since.get(person_id, now)
                if idle_duration >= IDLE_THRESHOLD_SECONDS and person_id not in _idle_commented:
                    minutes = int(idle_duration // 60)
                    _maybe_comment(f"{display} has been in the same state for about {minutes} minutes.")
                    _idle_commented.add(person_id)

    # Departures - someone tracked last check who's gone now
    for person_id, info in _previous_people.items():
        if person_id not in people:
            name = info.get("name", "unknown")
            display = name if name != "unknown" else f"person {person_id}"
            _maybe_comment(f"{display} left the view.")
            _state_since.pop(person_id, None)
            _idle_commented.discard(person_id)

    _previous_people.clear()
    _previous_people.update(people)


def main():
    print(f"Watching {SCENE_STATE_PATH} for meaningful scene changes to comment on.")
    print(f"Poll interval: {POLL_INTERVAL}s. Minimum gap between comments: {AMBIENT_MIN_GAP_SECONDS}s.")
    print("Depends on Gemini/network - silently skips commenting if unavailable.")
    print("Ctrl+C to stop.\n")

    try:
        while True:
            scene_data = read_scene_state()
            if scene_data:
                check_for_changes(scene_data)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()