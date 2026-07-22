"""
Baseline GPU test: camera + object detection + pose detection combined,
on this new machine, before adding the tracker.

This mirrors your old step1-4 from the CPU laptop, but running on GPU now.
Confirms:
  - camera opens
  - YOLOv8n object detection draws boxes+labels
  - YOLOv8n-Pose draws skeletons
  - both run together on the same frame
  - FPS is now much higher than the CPU laptop (watch the overlay)

Press 'q' to quit.
"""

import cv2
import time
from ultralytics import YOLO

OBJECT_MODEL_PATH = "yolov8n.pt"
POSE_MODEL_PATH = "yolov8n-pose.pt"
OBJECT_CONFIDENCE_THRESHOLD = 0.25

def main():
    print("Loading models onto GPU...")
    object_model = YOLO(OBJECT_MODEL_PATH)
    pose_model = YOLO(POSE_MODEL_PATH)

    # Force models onto GPU explicitly
    object_model.to("cuda")
    pose_model.to("cuda")
    print("Models loaded on GPU.")

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: could not open camera")
        return

    prev_time = time.time()
    fps = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        # Run both models on the same frame
        object_results = object_model(frame, conf=OBJECT_CONFIDENCE_THRESHOLD,
                                       verbose=False, device="cuda")
        pose_results = pose_model(frame, verbose=False, device="cuda")

        # Draw object boxes first
        annotated = object_results[0].plot()
        # Draw pose skeletons on top of that same frame
        annotated = pose_results[0].plot(img=annotated)

        # FPS calculation
        curr_time = time.time()
        fps = 1.0 / (curr_time - prev_time) if curr_time != prev_time else fps
        prev_time = curr_time

        cv2.putText(annotated, f"FPS: {fps:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        cv2.imshow("Baseline GPU Test - Object + Pose", annotated)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()