"""
Bridge Health Monitor
--------------------------
Run this in a THIRD terminal window while both the vision pipeline and
main.py are running. It continuously re-reads scene_state.json and
prints its age and contents every second, so you can watch in real time
whether the vision pipeline is actively writing fresh data.

This proves the "connection" between your two systems the same way a
person would check it: is the file actually changing right now, or is
it frozen/stale?

Run:
    python bridge_monitor.py
Stop:
    Ctrl+C
"""

import json
import time
import os

SCENE_STATE_PATH = "../vision_pipeline/scene_state.json"
CHECK_INTERVAL = 1.0

last_timestamp_seen = None

print("Watching scene_state.json for live updates. Ctrl+C to stop.\n")

try:
    while True:
        if not os.path.exists(SCENE_STATE_PATH):
            print("STATUS: file does not exist at all - check the path or "
                  "whether the vision pipeline has run at least once.")
        else:
            try:
                with open(SCENE_STATE_PATH, "r") as f:
                    data = json.load(f)
                timestamp = data.get("timestamp", 0)
                age = time.time() - timestamp

                if timestamp == last_timestamp_seen:
                    status = "UNCHANGED since last check - vision pipeline may not be running/writing"
                else:
                    status = "UPDATED - vision pipeline is actively writing"
                    last_timestamp_seen = timestamp

                people = data.get("people", {})
                print(f"[{time.strftime('%H:%M:%S')}] age={age:.1f}s | {status}")
                print(f"    people currently in data: {people}\n")

            except (json.JSONDecodeError, OSError) as e:
                print(f"STATUS: error reading file (may be mid-write): {e}")

        time.sleep(CHECK_INTERVAL)

except KeyboardInterrupt:
    print("\nStopped.")