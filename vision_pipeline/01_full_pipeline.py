"""
Full merged pipeline: object detection + pose + tracker (GPU) combined
with face recognition (CPU), producing structured scene state written to
scene_state.json.

This pipeline is a PURE SENSOR - it only writes JSON. It never speaks or
decides what to say; that's main.py's job (in jd_robot_system), which
reads this file fresh and combines it with Gemini for any spoken output.

BEFORE RUNNING:
  - Make sure known_encodings.pkl exists (run enroll_faces.py first)
  - Update HOLDABLE_LABELS if you want to tune which objects count as "held"

Press 'q' to quit.
"""

import cv2
import time
import os
import pickle
import numpy as np
from collections import defaultdict
from ultralytics import YOLO

try:
    import face_recognition
except ImportError:
    print("ERROR: face_recognition not installed. Run: pip install face_recognition")
    raise

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
import socket

ARC_HOST = "127.0.0.1"
ARC_PORT = 6666
SNAPSHOT_FOLDER = None  # set in main() using os.path.expanduser

OBJECT_MODEL_PATH = "yolov8m.pt"
POSE_MODEL_PATH = "yolov8m-pose.pt"
OBJECT_CONFIDENCE_THRESHOLD = 0.25
PERSON_CONFIDENCE_THRESHOLD = 0.35

KNOWN_ENCODINGS_FILE = os.path.join("..", "setup", "known_encodings.pkl")
KNOWN_ENCODINGS_FILE_FALLBACK = "known_encodings.pkl"
FACE_RECHECK_INTERVAL = 3
FACE_MATCH_TOLERANCE = 0.6

PROXIMITY_MARGIN = 30
FRAMES_TO_CONFIRM = 2
FRAMES_TO_CLEAR = 2

HOLDABLE_LABELS = {
    "cell phone", "cup", "bottle", "book", "remote", "mouse", "keyboard",
    "scissors", "banana", "apple", "orange", "sandwich", "sports ball",
    "wine glass", "fork", "knife", "spoon", "bowl", "teddy bear",
    "umbrella", "handbag", "backpack", "toothbrush", "hair drier",
    "frisbee", "tennis racket", "baseball bat", "baseball glove",
    "skateboard", "tie", "suitcase","laptop", "tv", "microwave", "oven", "toaster", "sink", "refrigerator","phone"
}

SITTABLE_LABELS = {"chair", "couch", "bench"}
SITTING_PROXIMITY_MARGIN = 40

LEFT_WRIST = 9
RIGHT_WRIST = 10

POSTURE_CONFIDENCE_WINDOW = 0.6
SUMMARY_INTERVAL = 2.0
DEBUG_POSTURE_LOG_FILE = "posture_debug.log"

# ---------------------------------------------------------------------------
# STATE (per track_id)
# ---------------------------------------------------------------------------
track_names = {}
track_last_face_check = {}
track_holding_state = defaultdict(lambda: {"candidate": None, "confirm_count": 0,
                                            "clear_count": 0, "confirmed": None})
track_posture_history = defaultdict(list)
track_posture_confirmed = {}

MIN_REQUEST_INTERVAL = 0.1
_last_request_time = [0.0]


def trigger_and_get_snapshot(sock, snapshot_folder, last_seen_file, max_wait=1.0):
    elapsed_since_last = time.time() - _last_request_time[0]
    if elapsed_since_last < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed_since_last)
    _last_request_time[0] = time.time()

    message = 'controlCommand("Camera Snapshot", "CameraSnapshot")\n'
    sock.sendall(message.encode("utf-8"))

    newest = None
    waited = 0.0
    while waited < max_wait:
        if os.path.isdir(snapshot_folder):
            files = [os.path.join(snapshot_folder, f) for f in os.listdir(snapshot_folder)]
            if files:
                candidate = max(files, key=os.path.getmtime)
                if candidate != last_seen_file:
                    newest = candidate
                    break
        time.sleep(0.05)
        waited += 0.05

    if newest is None:
        return None, last_seen_file

    frame = None
    for attempt in range(10):
        try:
            frame = cv2.imread(newest)
        except cv2.error:
            frame = None
        if frame is not None:
            break
        time.sleep(0.05)

    for f in os.listdir(snapshot_folder):
        full_path = os.path.join(snapshot_folder, f)
        if full_path != newest:
            try:
                os.remove(full_path)
            except OSError:
                pass

    if frame is None:
        return None, newest

    return frame, newest


track_height_baseline = {}
STANDING_RATIO_THRESHOLD = 0.85
SITTING_RATIO_THRESHOLD = 0.65
BASELINE_DECAY = 0.995


def detect_posture_relative(track_id, person_bbox):
    x1, y1, x2, y2 = person_bbox
    height = abs(y2 - y1)

    baseline = track_height_baseline.get(track_id, height)
    if height > baseline:
        baseline = height
    else:
        baseline = baseline * BASELINE_DECAY + height * (1 - BASELINE_DECAY)
    track_height_baseline[track_id] = baseline

    if baseline < 1e-3:
        return "unknown", "no baseline yet"

    ratio = height / baseline
    debug_info = f"height={height:.0f} baseline={baseline:.0f} ratio={ratio:.2f}"

    if ratio >= STANDING_RATIO_THRESHOLD:
        return "standing", debug_info
    elif ratio <= SITTING_RATIO_THRESHOLD:
        return "sitting", debug_info
    return "unknown", debug_info


def get_confident_posture(track_id, raw_posture, now):
    history = track_posture_history[track_id]
    history.append((now, raw_posture))

    cutoff = now - POSTURE_CONFIDENCE_WINDOW
    while history and history[0][0] < cutoff:
        history.pop(0)

    non_unknown = [p for _, p in history if p != "unknown"]
    if not non_unknown:
        return None

    span_covered = now - history[0][0]
    all_same = len(set(non_unknown)) == 1

    if span_covered >= POSTURE_CONFIDENCE_WINDOW and all_same:
        confident = non_unknown[0]
        track_posture_confirmed[track_id] = confident
        return confident

    return None


import json
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCENE_STATE_FILE = os.path.join(BASE_DIR, "scene_state.json")


def cleanup_stale_tmp_files():
    """Removes leftover .tmp files from previous crashed/interrupted runs
    (a crash mid-write can leave an orphan temp file behind since the
    rename-to-scene_state.json step never ran) so they don't pile up next
    to scene_state.json over time."""
    try:
        for f in os.listdir(BASE_DIR):
            if f.startswith("tmp") and f.endswith(".tmp"):
                try:
                    os.remove(os.path.join(BASE_DIR, f))
                except OSError:
                    pass
    except OSError:
        pass


def write_scene_state_json(scene_state, object_labels):
    """Writes the current scene state to a JSON file atomically. This is
    the ONLY output of this pipeline - no speaking, no decisions."""
    visible_objects = list(dict.fromkeys([l for l in object_labels if l != "person"]))
    data = {
        "timestamp": time.time(),
        "objects_visible": visible_objects,
        "people": {
            str(tid): {
                "name": info["name"],
                "posture": info["posture"],
                "sitting_on": info.get("sitting_on"),
                "holding": info["holding"],
            }
            for tid, info in scene_state.items()
        },
    }
    try:
        dir_name = os.path.dirname(os.path.abspath(SCENE_STATE_FILE)) or "."
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as tmp_f:
            json.dump(data, tmp_f, indent=2)
            tmp_path = tmp_f.name
        os.replace(tmp_path, SCENE_STATE_FILE)
    except OSError:
        pass


track_sitting_state = defaultdict(lambda: {"candidate": None, "confirm_count": 0,
                                            "clear_count": 0, "confirmed": None})


def check_sitting_on(track_id, person_bbox, object_boxes, object_labels):
    px1, py1, px2, py2 = person_bbox
    state = track_sitting_state[track_id]
    found_furniture = None

    for (ox1, oy1, ox2, oy2), label in zip(object_boxes, object_labels):
        if label not in SITTABLE_LABELS:
            continue
        overlap_x = px1 - SITTING_PROXIMITY_MARGIN <= ox2 and ox1 <= px2 + SITTING_PROXIMITY_MARGIN
        overlap_y = py1 - SITTING_PROXIMITY_MARGIN <= oy2 and oy1 <= py2 + SITTING_PROXIMITY_MARGIN
        if overlap_x and overlap_y:
            found_furniture = label
            break

    if found_furniture:
        if state["candidate"] == found_furniture:
            state["confirm_count"] += 1
        else:
            state["candidate"] = found_furniture
            state["confirm_count"] = 1
        state["clear_count"] = 0
        if state["confirm_count"] >= FRAMES_TO_CONFIRM:
            state["confirmed"] = found_furniture
    else:
        state["clear_count"] += 1
        if state["clear_count"] >= FRAMES_TO_CLEAR:
            state["confirmed"] = None
            state["candidate"] = None
            state["confirm_count"] = 0

    return state["confirmed"]


def load_known_faces():
    path = KNOWN_ENCODINGS_FILE if os.path.exists(KNOWN_ENCODINGS_FILE) else KNOWN_ENCODINGS_FILE_FALLBACK
    print(f"Loading known faces from: {os.path.abspath(path)}")
    with open(path, "rb") as f:
        data = pickle.load(f)
    return data["names"], data["encodings"]


def match_face_to_name(face_encoding, known_names, known_encodings):
    if len(known_encodings) == 0:
        return "unknown"
    distances = face_recognition.face_distance(known_encodings, face_encoding)
    best_idx = np.argmin(distances)
    if distances[best_idx] <= FACE_MATCH_TOLERANCE:
        return known_names[best_idx]
    return "unknown"


def find_closest_face(face_locations, person_bbox):
    px1, py1, px2, py2 = person_bbox
    best_idx = None
    best_dist = float("inf")
    for i, (top, right, bottom, left) in enumerate(face_locations):
        face_cx = (left + right) / 2
        face_cy = (top + bottom) / 2
        if px1 - 20 <= face_cx <= px2 + 20 and py1 - 20 <= face_cy <= py2 + 20:
            person_cx = (px1 + px2) / 2
            person_top_cy = py1 + (py2 - py1) * 0.15
            dist = (face_cx - person_cx) ** 2 + (face_cy - person_top_cy) ** 2
            if dist < best_dist:
                best_dist = dist
                best_idx = i
    return best_idx


def check_holding(track_id, wrist_points, object_boxes, object_labels):
    state = track_holding_state[track_id]
    found_object = None

    for (wx, wy) in wrist_points:
        if wx is None:
            continue
        for (ox1, oy1, ox2, oy2), label in zip(object_boxes, object_labels):
            if label not in HOLDABLE_LABELS:
                continue
            near = (ox1 - PROXIMITY_MARGIN <= wx <= ox2 + PROXIMITY_MARGIN and
                    oy1 - PROXIMITY_MARGIN <= wy <= oy2 + PROXIMITY_MARGIN)
            if near:
                found_object = label
                break
        if found_object:
            break

    if found_object:
        if state["candidate"] == found_object:
            state["confirm_count"] += 1
        else:
            state["candidate"] = found_object
            state["confirm_count"] = 1
        state["clear_count"] = 0
        if state["confirm_count"] >= FRAMES_TO_CONFIRM:
            state["confirmed"] = found_object
    else:
        state["clear_count"] += 1
        if state["clear_count"] >= FRAMES_TO_CLEAR:
            state["confirmed"] = None
            state["candidate"] = None
            state["confirm_count"] = 0

    return state["confirmed"]


def main():
    cleanup_stale_tmp_files()

    print("Loading known faces...")
    known_names, known_encodings = load_known_faces()
    print(f"Loaded {len(known_names)} known face(s): {', '.join(known_names)}")

    print(f"Loading models onto GPU... (object={OBJECT_MODEL_PATH}, pose={POSE_MODEL_PATH})")
    for path in [OBJECT_MODEL_PATH, POSE_MODEL_PATH]:
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  -> {path}: {size_mb:.1f} MB (found locally, {os.path.abspath(path)})")
        else:
            print(f"  -> {path}: NOT FOUND LOCALLY - will attempt download")
    object_model = YOLO(OBJECT_MODEL_PATH)
    pose_model = YOLO(POSE_MODEL_PATH)
    object_model.to("cuda")
    pose_model.to("cuda")
    print("Models loaded.")

    global SNAPSHOT_FOLDER
    SNAPSHOT_FOLDER = os.path.join(os.path.expanduser("~"), "Pictures", "My Robot Pictures")

    print(f"Connecting to ARC over TCP at {ARC_HOST}:{ARC_PORT} ...")
    sock = socket.create_connection((ARC_HOST, ARC_PORT), timeout=5)
    print("Connected. Using Camera Snapshot skill to pull frames.")
    print(f"Snapshot folder: {SNAPSHOT_FOLDER}")
    print("This pipeline only writes scene_state.json - no speech, no ARC actions.\n")

    last_seen_file = None
    frame_count = 0
    last_summary_time = [0.0]
    prev_time = time.time()
    fps = 0

    while True:
        frame, last_seen_file = trigger_and_get_snapshot(sock, SNAPSHOT_FOLDER, last_seen_file)
        if frame is None:
            continue
        frame_count += 1

        object_results = object_model(frame, conf=OBJECT_CONFIDENCE_THRESHOLD,
                                       verbose=False, device="cuda")[0]
        object_boxes = []
        object_labels = []
        if object_results.boxes is not None:
            for box in object_results.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                label = object_model.names[int(box.cls[0])]
                object_boxes.append((x1, y1, x2, y2))
                object_labels.append(label)

        pose_results = pose_model.track(frame, persist=True, conf=PERSON_CONFIDENCE_THRESHOLD,
                                         tracker="bytetrack.yaml", verbose=False, device="cuda")[0]

        annotated = object_results.plot()
        annotated = pose_results.plot(img=annotated)

        scene_state = {}

        if pose_results.boxes is not None and pose_results.boxes.id is not None:
            track_ids = pose_results.boxes.id.int().tolist()
            person_boxes = pose_results.boxes.xyxy.tolist()
            keypoints_all = pose_results.keypoints.xy.tolist() if pose_results.keypoints is not None else []

            need_face_check = any(
                (tid not in track_names) or
                (frame_count - track_last_face_check.get(tid, -999) >= FACE_RECHECK_INTERVAL)
                for tid in track_ids
            )

            face_locations = []
            face_encodings = []
            if need_face_check:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                face_locations = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=2)
                if face_locations:
                    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

            for i, tid in enumerate(track_ids):
                person_bbox = person_boxes[i]

                needs_check = (tid not in track_names) or \
                               (frame_count - track_last_face_check.get(tid, -999) >= FACE_RECHECK_INTERVAL)
                if needs_check and face_locations:
                    match_idx = find_closest_face(face_locations, person_bbox)
                    if match_idx is not None:
                        name = match_face_to_name(face_encodings[match_idx], known_names, known_encodings)
                        track_names[tid] = name
                        track_last_face_check[tid] = frame_count
                elif tid not in track_names:
                    track_names[tid] = "unknown"

                name = track_names.get(tid, "unknown")

                wrist_points = [(None, None), (None, None)]
                if i < len(keypoints_all):
                    kpts = keypoints_all[i]
                    if len(kpts) > RIGHT_WRIST:
                        wrist_points = [tuple(kpts[LEFT_WRIST]), tuple(kpts[RIGHT_WRIST])]

                held_object = check_holding(tid, wrist_points, object_boxes, object_labels)
                sitting_on = check_sitting_on(tid, person_bbox, object_boxes, object_labels)

                raw_posture, posture_debug = detect_posture_relative(tid, person_bbox)
                confident_posture = get_confident_posture(tid, raw_posture, time.time())

                try:
                    with open(DEBUG_POSTURE_LOG_FILE, "a") as dbg_f:
                        dbg_f.write(f"{name} (id {tid}): raw={raw_posture} "
                                    f"confident={confident_posture} ({posture_debug})\n")
                except OSError:
                    pass

                scene_state[tid] = {"name": name, "holding": held_object,
                                     "posture": confident_posture or "uncertain",
                                     "sitting_on": sitting_on}

                x1, y1, x2, y2 = person_bbox
                posture_display = f"sitting at {sitting_on}" if sitting_on else (confident_posture or "...")
                label_text = f"{name} | {posture_display}"
                if held_object:
                    label_text += f" | holding: {held_object}"
                cv2.putText(annotated, label_text, (int(x1), int(y1) - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # ONLY output of this pipeline.
        write_scene_state_json(scene_state, object_labels)

        now = time.time()
        if now - last_summary_time[0] >= SUMMARY_INTERVAL:
            num_people = len(scene_state)
            num_objects = len(set(l for l in object_labels if l != "person"))
            print(f"[Scene] {num_people} person(s), {num_objects} object(s) detected")
            last_summary_time[0] = now

        curr_time = time.time()
        fps = 1.0 / (curr_time - prev_time) if curr_time != prev_time else fps
        prev_time = curr_time
        cv2.putText(annotated, f"FPS: {fps:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        cv2.namedWindow("JD Vision Pipeline - Object+Pose+Tracker+Face", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("JD Vision Pipeline - Object+Pose+Tracker+Face", 960, 720)
        cv2.imshow("JD Vision Pipeline - Object+Pose+Tracker+Face", annotated)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    sock.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()