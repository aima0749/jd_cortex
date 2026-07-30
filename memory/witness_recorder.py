"""
Witness recorder - the process that gives JD a memory.

Runs alongside the vision pipeline, reads its only output
(vision_pipeline/scene_state.json), and turns raw per-frame sightings
into a small number of meaningful diary events: who arrived, who left
and after how long, what a known person was holding or sitting on, and
which objects came into view. Those events are what the Gemini prompt
later answers memory questions from.

Identity is tracked by NAME, never by the pipeline's track ids - the
same person can burn through dozens of ids in a minute (the old
activity log is thirty lines of exactly that), so every unrecognized
sighting pools into one "unknown" bucket and each named person is one
entry. An arrival needs a couple of seconds of continuous presence
before it counts, and a departure needs a solid gap, which is what
keeps the diary readable instead of flapping.

This process never opens its own ARC connection. With JD_ANNOUNCE=on it
drops arrival announcements into speech_queue.json and main.py's alert
thread speaks them - one speaker, one owner, same rule as before.

Run (its own terminal, vision pipeline can start before or after):
    python memory/witness_recorder.py
Selftest (pure logic plus a throwaway database, no camera needed):
    python memory/witness_recorder.py selftest
"""

import json
import os
import sys
import time

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_BASE_DIR, ".."))
for _path in (_REPO_ROOT, os.path.join(_REPO_ROOT, "jd_robot_system")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from memory import witness_store
import speech_queue

SCENE_STATE_PATH = os.environ.get(
    "JD_SCENE_STATE",
    os.path.join(_REPO_ROOT, "vision_pipeline", "scene_state.json"),
)

POLL_INTERVAL = 1.0
STATE_STALE_SECS = 10.0       # matches scene_context.MAX_AGE_SECONDS
ARRIVE_CONFIRM_SECS = 2.0     # continuous presence before "arrived" is real
LEAVE_CONFIRM_SECS = 12.0     # continuous absence before "left" is real
RELOG_GAP_SECS = 300.0        # same held object / furniture / ambient object
                              # is only re-logged after this quiet gap
ANNOUNCE = os.environ.get("JD_ANNOUNCE", "off").strip().lower() == "on"
ANNOUNCE_COOLDOWN_SECS = 120.0


def group_people(raw_people):
    """Collapses the pipeline's per-track-id people dict into a per-name
    view. All unrecognized ids pool under "unknown" with a count; for a
    named person the first non-empty holding/sitting value wins."""
    grouped = {}
    for info in (raw_people or {}).values():
        name = (info.get("name") or "").strip().lower()
        if not name:
            name = "unknown"
        entry = grouped.setdefault(name, {"count": 0, "holding": None, "sitting_on": None})
        entry["count"] += 1
        if name != "unknown":
            if info.get("holding") and not entry["holding"]:
                entry["holding"] = info["holding"]
            if info.get("sitting_on") and not entry["sitting_on"]:
                entry["sitting_on"] = info["sitting_on"]
    return grouped


def humanize_duration(seconds):
    seconds = max(0, int(round(seconds)))
    if seconds < 90:
        return f"{seconds} seconds"
    minutes = int(round(seconds / 60))
    if minutes < 90:
        return f"{minutes} minutes"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def advance_presence(presence, grouped, now,
                     arrive_secs=ARRIVE_CONFIRM_SECS,
                     leave_secs=LEAVE_CONFIRM_SECS,
                     relog_gap=RELOG_GAP_SECS):
    """The whole brain of the recorder, kept pure (no files, no clock,
    no sockets) so the selftest can drive it with fake snapshots.

    presence: mutable dict name -> tracking state, owned by the caller.
    Returns (events, announcements). Each event is a (kind, person,
    detail, text) tuple ready for the store; each announcement is a
    (name, spoken_line) pair for the optional speech queue.
    """
    events = []
    announcements = []

    for name, seen in grouped.items():
        p = presence.get(name)
        if p is None:
            p = presence[name] = {
                "present": False,
                "first_glimpse": now,
                "arrived_at": None,
                "last_seen": now,
                "holding_logged": (None, 0.0),
                "sitting_logged": (None, 0.0),
                "max_count": seen["count"],
            }
        p["last_seen"] = now
        p["max_count"] = max(p["max_count"], seen["count"])

        if not p["present"] and now - p["first_glimpse"] >= arrive_secs:
            p["present"] = True
            p["arrived_at"] = now
            if name == "unknown":
                label = ("an unknown person" if p["max_count"] <= 1
                         else f"{p['max_count']} unknown people")
                events.append(("arrived", name, str(p["max_count"]), f"{label} arrived"))
                announcements.append((name, "I can see someone I don't recognize."))
            else:
                events.append(("arrived", name, None, f"{name} arrived"))
                announcements.append((name, f"I can see {name}."))

        # Holding/sitting only mean anything for a named, confirmed-present
        # person - "an unknown holding a cup" isn't attributable to anyone
        # once ids churn. Same object again is only re-logged after a quiet
        # gap, so a flickering detection doesn't fill the diary with the
        # same cup twenty times.
        if p["present"] and name != "unknown":
            if seen["holding"]:
                last_obj, last_ts = p["holding_logged"]
                if seen["holding"] != last_obj or now - last_ts >= relog_gap:
                    events.append(("holding", name, seen["holding"],
                                   f"{name} was holding a {seen['holding']}"))
                p["holding_logged"] = (seen["holding"], now)
            if seen["sitting_on"]:
                last_obj, last_ts = p["sitting_logged"]
                if seen["sitting_on"] != last_obj or now - last_ts >= relog_gap:
                    events.append(("sitting", name, seen["sitting_on"],
                                   f"{name} sat on the {seen['sitting_on']}"))
                p["sitting_logged"] = (seen["sitting_on"], now)

    for name in list(presence.keys()):
        p = presence[name]
        if now - p["last_seen"] >= leave_secs:
            if p["present"]:
                # Measured to the last real sighting - the absence gap that
                # confirmed the departure was time they were already gone.
                duration = humanize_duration(p["last_seen"] - p["arrived_at"])
                if name == "unknown":
                    label = ("the unknown person" if p["max_count"] <= 1
                             else "the unknown people")
                    events.append(("left", name, str(p["max_count"]),
                                   f"{label} left after {duration}"))
                else:
                    events.append(("left", name, None, f"{name} left after {duration}"))
            # Dropping the entry re-arms the arrival debounce for their
            # next appearance - a brief glimpse that never confirmed just
            # vanishes without any event, which is the point.
            del presence[name]

    return events, announcements


def advance_objects(object_state, labels_now, now,
                    arrive_secs=ARRIVE_CONFIRM_SECS,
                    leave_secs=LEAVE_CONFIRM_SECS,
                    relog_gap=RELOG_GAP_SECS):
    """Same debounce idea for ambient objects (objects_visible), but
    lighter: one "came into view" event per continuous appearance, no
    departure events - "the chair left" is noise nobody asked for."""
    events = []
    labels_now = set(labels_now or [])

    for label in labels_now:
        st = object_state.get(label)
        if st is None:
            st = object_state[label] = {"first_glimpse": now, "last_seen": now,
                                        "logged_at": None}
        st["last_seen"] = now
        if st["logged_at"] is None and now - st["first_glimpse"] >= arrive_secs:
            st["logged_at"] = now
            events.append(("object", None, label, f"a {label} came into view"))

    for label in list(object_state.keys()):
        st = object_state[label]
        if label not in labels_now and now - st["last_seen"] >= leave_secs:
            if st["logged_at"] is None or now - st["logged_at"] >= relog_gap:
                del object_state[label]
            else:
                # Recently logged: keep the entry a while so a flicker
                # doesn't produce a duplicate "came into view".
                st["first_glimpse"] = now

    return events


def read_snapshot(path, now):
    """Returns (grouped_people, object_labels, status). A missing,
    unreadable, or stale file reads as an empty scene - people and
    objects then time out through the normal leave debounce, which is
    exactly what should happen when vision goes away."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}, [], "missing"

    if now - data.get("timestamp", 0) > STATE_STALE_SECS:
        return {}, [], "stale"

    return group_people(data.get("people", {})), data.get("objects_visible", []), "live"


def main():
    removed = witness_store.prune_old_events()
    if removed:
        print(f"Pruned {removed} diary event(s) older than {witness_store.KEEP_DAYS:.0f} days.")
    witness_store.record_event("system", "witness recorder started")

    print(f"Watching:  {SCENE_STATE_PATH}")
    print(f"Diary:     {witness_store.DB_PATH}")
    print(f"Announce:  {'on' if ANNOUNCE else 'off'} (JD_ANNOUNCE)")
    print("Ctrl+C to stop.\n")

    presence = {}
    object_state = {}
    announce_after = {}
    last_status = None

    try:
        while True:
            now = time.time()
            grouped, labels, status = read_snapshot(SCENE_STATE_PATH, now)

            if status != last_status:
                notes = {
                    "live": "vision pipeline is live",
                    "stale": "scene_state.json has gone stale - is the vision pipeline still running?",
                    "missing": "scene_state.json not readable yet - waiting for the vision pipeline",
                }
                print(f"[{time.strftime('%H:%M:%S')}] {notes[status]}")
                last_status = status

            events, announcements = advance_presence(presence, grouped, now)
            events += advance_objects(object_state, labels, now)

            for kind, person, detail, text in events:
                witness_store.record_event(kind, text, person=person, detail=detail)
                print(f"  [{time.strftime('%H:%M:%S')}] {text}")

            if ANNOUNCE:
                for name, line in announcements:
                    if now >= announce_after.get(name, 0):
                        speech_queue.request_speech(line)
                        announce_after[name] = now + ANNOUNCE_COOLDOWN_SECS

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        still_here = sorted(n for n, p in presence.items() if p["present"])
        note = f" (was still seeing: {', '.join(still_here)})" if still_here else ""
        witness_store.record_event("system", f"witness recorder stopped{note}")
        print("\nStopped. Diary saved.")


def selftest():
    import tempfile

    passed = failed = 0

    def check(label, condition):
        nonlocal passed, failed
        print(f"  [{'ok' if condition else 'FAIL'}] {label}")
        passed += condition
        failed += not condition

    print("witness recorder selftest\n")

    grouped = group_people({
        "1": {"name": "name1", "holding": "cup", "sitting_on": None},
        "2": {"name": None, "holding": None, "sitting_on": None},
        "7": {"name": "unknown", "holding": "phone", "sitting_on": None},
    })
    check("unrecognized ids pool into one unknown bucket",
          grouped.get("unknown", {}).get("count") == 2)
    check("named person keeps their held object",
          grouped.get("name1", {}).get("holding") == "cup")
    check("unknown pool never claims a held object",
          grouped.get("unknown", {}).get("holding") is None)

    presence = {}
    see_name1 = {"name1": {"count": 1, "holding": None, "sitting_on": None}}
    events, _ = advance_presence(presence, see_name1, now=100.0)
    check("a first glimpse is not yet an arrival", events == [])
    events, ann = advance_presence(presence, see_name1, now=103.0)
    check("arrival confirms after continuous presence",
          any(e[0] == "arrived" and e[1] == "name1" for e in events))
    check("arrival produces one announcement",
          ann == [("name1", "I can see name1.")])

    events, _ = advance_presence(presence, {}, now=105.0)
    check("a brief dropout is not a departure", events == [])
    events, _ = advance_presence(presence, see_name1, now=106.0)
    check("reappearing after a dropout re-logs nothing", events == [])

    hold = {"name1": {"count": 1, "holding": "cup", "sitting_on": None}}
    events, _ = advance_presence(presence, hold, now=110.0)
    check("picking up an object is logged once",
          [e[0] for e in events] == ["holding"])
    events, _ = advance_presence(presence, hold, now=111.0)
    check("still holding the same object logs nothing", events == [])

    events, _ = advance_presence(presence, {}, now=130.0)
    left = [e for e in events if e[0] == "left"]
    check("departure confirms after a solid gap and carries a duration",
          len(left) == 1 and "seconds" in left[0][3])
    check("departed person is dropped so the debounce re-arms",
          "name1" not in presence)

    presence = {}
    two_unknown = {"unknown": {"count": 2, "holding": None, "sitting_on": None}}
    advance_presence(presence, two_unknown, now=200.0)
    events, _ = advance_presence(presence, two_unknown, now=203.0)
    check("multiple unknowns arrive with a count",
          any(e[3] == "2 unknown people arrived" for e in events))

    object_state = {}
    advance_objects(object_state, ["laptop"], now=300.0)
    events = advance_objects(object_state, ["laptop"], now=303.0)
    check("an object coming into view is logged once",
          [e[3] for e in events] == ["a laptop came into view"])
    events = advance_objects(object_state, ["laptop"], now=304.0)
    check("an object staying in view logs nothing", events == [])

    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        check("empty diary yields an empty context block",
              witness_store.diary_context(db_path=db_path) == "")

        base = time.time() - 600
        witness_store.record_event("arrived", "name1 arrived",
                                   person="name1", ts=base, db_path=db_path)
        witness_store.record_event("holding", "name1 was holding a cup",
                                   person="name1", detail="cup", ts=base + 60, db_path=db_path)
        rows = witness_store.recent_events(db_path=db_path)
        check("events round-trip through the store in order",
              len(rows) == 2 and rows[0][4] == "name1 arrived")

        block = witness_store.diary_context(db_path=db_path)
        check("diary context names the person and the object",
              "name1" in block and "cup" in block)
        check("diary context includes the seen-today summary",
              "Seen today:" in block or "Last seen on earlier days:" in block)

        for i in range(40):
            witness_store.record_event("object", f"a very long filler event number {i} came into view",
                                       ts=base + 120 + i, db_path=db_path)
        block = witness_store.diary_context(max_chars=400, db_path=db_path)
        check("diary context respects its size cap by trimming whole entries",
              len(block) <= 400 and "not shown" in block)
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    else:
        main()
