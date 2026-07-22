"""
Step: Face enrollment.

Put one clear photo per person in the known_faces/ folder, named after
them, e.g.:
    known_faces/aima.jpg
    known_faces/omar.jpg

Run this script whenever you add/change photos in that folder. It scans
every image, computes a face encoding (a 128-number "fingerprint" of the
face), and saves all of them into known_encodings.pkl.

The live pipeline script loads that .pkl file at startup and compares
faces it sees against these encodings - it does NOT re-read the images
live, so enrollment only needs to be re-run when you change the photos.

Tips for good enrollment photos:
  - One person per photo, face clearly visible, decent lighting
  - Front-facing or near-front-facing works best
  - Avoid sunglasses / heavy shadows on the face
  - JPG or PNG both fine
"""

import face_recognition
import os
import pickle

KNOWN_FACES_DIR = "known_faces"
OUTPUT_FILE = "known_encodings.pkl"

def main():
    if not os.path.isdir(KNOWN_FACES_DIR):
        print(f"ERROR: '{KNOWN_FACES_DIR}' folder not found. Create it and "
              f"add photos named like aima.jpg, omar.jpg, etc.")
        return

    names = []
    encodings = []

    files = [f for f in os.listdir(KNOWN_FACES_DIR)
              if f.lower().endswith((".jpg", ".jpeg", ".png"))]

    if not files:
        print(f"No image files found in '{KNOWN_FACES_DIR}'. Add photos and re-run.")
        return

    print(f"Found {len(files)} image(s). Processing...")

    for filename in files:
        name = os.path.splitext(filename)[0]  # "aima.jpg" -> "aima"
        path = os.path.join(KNOWN_FACES_DIR, filename)

        image = face_recognition.load_image_file(path)
        face_locations = face_recognition.face_locations(image)

        if len(face_locations) == 0:
            print(f"  [SKIP] {filename}: no face detected. Try a clearer photo.")
            continue
        if len(face_locations) > 1:
            print(f"  [WARN] {filename}: multiple faces detected, using the "
                  f"first one. Use a photo with only {name} in it for best results.")

        face_encoding = face_recognition.face_encodings(image, known_face_locations=[face_locations[0]])[0]
        names.append(name)
        encodings.append(face_encoding)
        print(f"  [OK] {filename} -> enrolled as '{name}'")

    if not names:
        print("No faces successfully enrolled. Fix the issues above and re-run.")
        return

    with open(OUTPUT_FILE, "wb") as f:
        pickle.dump({"names": names, "encodings": encodings}, f)

    print(f"\nEnrollment complete. {len(names)} face(s) saved to {OUTPUT_FILE}")
    print(f"Enrolled: {', '.join(names)}")


if __name__ == "__main__":
    main()