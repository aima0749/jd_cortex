"""
Surveillance Watcher
--------------------------
Runs standalone, alongside the vision pipeline and main.py. Polls
scene_state.json continuously and reacts to two conditions:

  1. UNKNOWN PERSON - present.
  2. SENSITIVE OBJECT - someone holding something flagged (knife, scissors).

FULLY OFFLINE - no Gemini call, no network dependency at all.

DEBOUNCED: each condition must persist for CONFIRM_POLLS consecutive
polls before it's treated as real - a single bad-lighting misdetection or
brief glimpse won't trigger anything.

Time-of-day awareness: alerts during typical sleeping hours get more
urgent wording - a cheap, offline stand-in for "judgment".

SNAPSHOTS: every time an event actually alerts (not every poll - only on
real, cooldown-gated alerts), a copy of vision_pipeline/latest_frame.jpg
is saved into snapshots/ with a timestamped filename. Bounded to the
MAX_SNAPSHOTS most recent - oldest ones auto-deleted, so storage never
grows unbounded no matter how long this runs.

On a confirmed event: appends a timestamped line to activity_log.txt and
QUEUES a spoken alert via speech_queue.py - this process does NOT open
its own ARC connection, only main.py does.

Run:
    python surveillance_watcher.py
Stop:
    Ctrl+C
"""

import json
import os
import time
from datetime import datetime

import speech_queue

SCENE_STATE_PATH = "../vision_pipeline/scene_state.json"
SNAPSHOT_REQUEST_PATH = "../vision_pipeline/snapshot_request.txt"

ACTIVITY_LOG_PATH = "activity_log.txt"
POLL_INTERVAL = 1.0
MAX_AGE_SECONDS = 10

SENSITIVE_OBJECTS = {"knife", "scissors"}

SENSITIVE_ALERT_UNKNOWN_ONLY = True
ALWAYS_WATCH_LIST = set()

UNKNOWN_CONFIRM_POLLS = 3
SENSITIVE_CONFIRM_POLLS = 3

UNKNOWN_ALERT_COOLDOWN_SECONDS = 120
SENSITIVE_ALERT_COOLDOWN_SECONDS = 60

NIGHT_START_HOUR = 22  # 10 PM
NIGHT_END_HOUR = 6     # 6 AM

_last_unknown_alert_time = [0.0]
_last_sensitive_alert_time = [0.0]
_unknown_poll_streak = [0]

sensitive_state = {}


def log_event(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(f"  [ALERT] {line}")
    with open(ACTIVITY_LOG_PATH, "a") as f:
        f.write(line + "\n")


def request_snapshot(reason_slug):
    """Drops a request for the vision pipeline to save its CURRENT frame
    directly to jd_robot_system/snapshots/ - no continuous per-frame
    writing on the vision pipeline's side, only saves an actual file
    when something real triggers it."""
    try:
        with open(SNAPSHOT_REQUEST_PATH, "w") as f:
            f.write(reason_slug)
    except OSError as e:
        print(f"  [snapshot] failed to request: {e}")


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


def _is_night():
    hour = datetime.now().hour
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR


def _handle_confirmed_unknown(unknown_ids):
    ready = (time.time() - _last_unknown_alert_time[0]) >= UNKNOWN_ALERT_COOLDOWN_SECONDS
    if not ready:
        return

    count = len(unknown_ids)
    if _is_night():
        speech_line = (
            "Alert! Unrecognized person detected at this hour!" if count == 1
            else f"Alert! {count} unrecognized people detected at this hour!"
        )
    else:
        speech_line = (
            "Who is this? I don't recognize you!" if count == 1
            else f"I don't recognize these {count} people!"
        )

    request_snapshot("unknown")
    message = f"Unknown person(s) detected (ids={unknown_ids}), night={_is_night()}"
    log_event(message)
    speech_queue.request_speech(speech_line)
    _last_unknown_alert_time[0] = time.time()


def _handle_confirmed_sensitive(person_id, name, holding):
    ready = (time.time() - _last_sensitive_alert_time[0]) >= SENSITIVE_ALERT_COOLDOWN_SECONDS
    if not ready:
        return

    who = name if name != "unknown" else f"person {person_id}"
    if _is_night():
        speech_line = f"Alert! {who} is holding a {holding} at this hour!"
    else:
        speech_line = f"Whoa, is that a {holding}?! Careful with that!"

    request_snapshot(f"sensitive_{holding}_id{person_id}")
    message = f"{who} is holding a {holding}, night={_is_night()}"
    log_event(message)
    speech_queue.request_speech(speech_line)
    _last_sensitive_alert_time[0] = time.time()


def check_and_alert(scene_data):
    people = scene_data.get("people", {})
    active_ids = set(people.keys())

    unknown_ids = [pid for pid, info in people.items() if info.get("name", "unknown") == "unknown"]

    if unknown_ids:
        _unknown_poll_streak[0] += 1
        if _unknown_poll_streak[0] == UNKNOWN_CONFIRM_POLLS:
            _handle_confirmed_unknown(unknown_ids)
    else:
        _unknown_poll_streak[0] = 0

    for person_id, info in people.items():
        state = sensitive_state.setdefault(person_id, {"holding_streak": 0, "alerted_for": None})
        name = info.get("name", "unknown")
        holding = info.get("holding")

        should_check_sensitive = (
            name == "unknown" or not SENSITIVE_ALERT_UNKNOWN_ONLY or name in ALWAYS_WATCH_LIST
        )

        if holding in SENSITIVE_OBJECTS and should_check_sensitive:
            if state["alerted_for"] == holding:
                state["holding_streak"] += 1
                continue
            state["holding_streak"] += 1
            if state["holding_streak"] >= SENSITIVE_CONFIRM_POLLS:
                _handle_confirmed_sensitive(person_id, name, holding)
                state["alerted_for"] = holding
        else:
            state["holding_streak"] = 0
            state["alerted_for"] = None

    for person_id in list(sensitive_state.keys()):
        if person_id not in active_ids:
            del sensitive_state[person_id]


def main():
    print(f"Watching {SCENE_STATE_PATH} for unknown people and sensitive objects.")
    print(f"Persistence required: {UNKNOWN_CONFIRM_POLLS} polls (unknown), "
          f"{SENSITIVE_CONFIRM_POLLS} polls (sensitive object).")
    print("Snapshots are saved by the vision pipeline (jd_robot_system/snapshots/) on real alerts.")
    print("Fully offline - no Gemini/network dependency in this process.")
    print(f"Logging to {ACTIVITY_LOG_PATH}. Speech alerts queued for main.py to speak.")
    print("Ctrl+C to stop.\n")

    try:
        while True:
            scene_data = read_scene_state()
            if scene_data:
                check_and_alert(scene_data)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()