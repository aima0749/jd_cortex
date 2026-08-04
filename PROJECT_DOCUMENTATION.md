# JD Robot Cortex — Project Documentation

This repository implements a helper system for controlling a JD humanoid robot through Synthiam ARC. It is built around safe robot command execution, speech output, optional vision-based scene awareness, and optional natural language understanding via Google Gemini.

## Non-technical overview

For non-programmers, think of this project as a set of helpers that let your JD robot:

- hear commands from you either by typing or by speaking,
- think a little about what you said,
- speak back to you through its speaker,
- move its body, play sounds, or light up in safe ways,
- watch the scene with a camera and notice who is there and what they are doing,
- alert you if something unusual happens, like an unknown person or a knife in view.

The code is split into pieces so each one has a simple job:

- one piece listens for your commands and sends them to the robot,
- one piece makes the robot talk,
- one piece looks at camera images and writes down what it sees,
- other pieces read those notes and decide whether to say something or raise an alert.

This means the robot can keep its sensing, talking, and acting separate, which makes it easier to understand and safer to use.

## Architecture overview

The system is intentionally decoupled into several cooperating processes:

- `jd_robot_system/main.py` — the primary command loop and ARC controller.
- `vision_pipeline/01_full_pipeline.py` — the sensor pipeline that reads camera frames, detects people and objects, and writes structured scene state.
- `jd_robot_system/surveillance_watcher.py` — offline scene monitoring for safety alerts.
- `jd_robot_system/ambient_watcher.py` — optional social commenting based on scene changes.
- `jd_robot_system/voice_parakeet.py` — local push-to-talk speech recognition.
- `jd_robot_system/tts.py` — text-to-speech output through ARC.

A typical deployment can use `start_jd.bat` to launch these pieces in separate windows, while keeping ARC as the single central robot controller.

## Data flow

1. The vision pipeline requests camera snapshots from ARC and converts them into structured scene state.
2. It writes `vision_pipeline/scene_state.json` and optionally saves snapshot images when requested.
3. `jd_robot_system/main.py` reads that scene state on demand through `scene_context.py`.
4. User commands arrive via typing or local microphone voice input.
5. The main loop either matches the command locally against a safe action list or forwards it to Gemini for understanding.
6. If Gemini returns a natural reply, `main.py` speaks it through ARC using `tts.py`.
7. If an action is suggested, `main.py` validates it against known actions before sending it to ARC.
8. Separate watcher processes also read `scene_state.json` and queue speech messages through `speech_queue.py`.
9. Only `main.py` opens an ARC connection for speaking, ensuring a single process owns the speaker.

This separation keeps sensing, decision-making, and actuation distinct, which simplifies safety reasoning and reduces cross-process contention.

## Repository layout

- `jd_robot_system/` — main control, Gemini integration, TTS, local voice, scene context, and helper utilities.
- `vision_pipeline/` — camera snapshot acquisition, detection, tracking, face recognition, and scene state output.
- `setup/` — face enrollment and setup helpers.
- `voice_model/` — placeholder for Parakeet model assets required by local speech recognition.
- `start_jd.bat` — Windows launcher that starts the vision pipeline, main program, and watcher processes.
- `requirements.txt` — Python dependencies for vision, speech, and Gemini integration.

## Main program (`jd_robot_system/main.py`)

### Role

`main.py` is the orchestrator that:

- connects to ARC over TCP using `jd_robot_system/arc_connection.py`,
- chooses the input mode (typed or local voice),
- processes every command,
- speaks replies,
- executes safe robot actions,
- handles queued speech from auxiliary watchers.

### ARC connection

`jd_robot_system/arc_connection.py` maintains a single TCP socket to ARC. All ARC commands are sent through this one connection, and it is opened only once per `main.py` run.

### Input modes

- **Typed mode**: the user types commands in the console.
- **Voice mode**: `voice_parakeet.listen_for_command()` waits for Enter, records until silence, and transcribes with a local Parakeet model.

### Command processing flow

For each input:

1. `main.py` checks for forget/reset phrases and clears short-term memory if requested.
2. It tries a local literal match against known movements, sounds, and lights.
3. If a local match succeeds, the action is validated and executed immediately.
4. If no local match is found, the command is sent to `gemini_brain.understand()`.
5. `understand()` builds a prompt that includes:
   - the user's text,
   - the current scene summary from `scene_context.py` (if available),
   - the known safe actions from `known_actions.describe_all_known()`,
   - recent conversation history from `conversation_memory.py`.
6. Gemini returns a short spoken reply and an optional matched action.
7. `main.py` speaks the reply via `tts.speak()`.
8. If an action is suggested, it is validated again against `known_actions.py` before executing.

### Safety and validation

The system uses a whitelist of permissible actions in `jd_robot_system/known_actions.py`:

- `MOVEMENTS` — pre-approved Auto Position actions.
- `SOUNDS` — valid soundboard track numbers.
- `LIGHTS` — valid RGB Animator effects.

Gemini may suggest an action, but the system never executes it without checking that it matches one of those known entries.

## Action execution and speech

### Robot actions

`known_actions.py` translates safe commands into ARC `ControlCommand(...)` calls:

- movements use `ControlCommand("Auto Position", AutoPositionAction, "<title>")`,
- sounds use `ControlCommand("Soundboard v4", Track_<n>)`,
- lights use `ControlCommand("RGB Animator", AutoPositionAction, "<title>")`.

After a movement, `main.py` optionally returns the robot to the `Standing` pose to avoid leaving it in an awkward position.

### Speech output

`jd_robot_system/tts.py` sends `SayWait(...)` via ARC and blocks until ARC acknowledges. It also sets a `speaking_flag` so local microphone recording does not begin while JD is still speaking.

### Cross-process speech queue

`jd_robot_system/speech_queue.py` implements a simple file-backed queue (`speech_queue.json`).

- watcher processes append messages to the file using `request_speech()`.
- `main.py` polls `speech_queue.pop_pending_messages()` on a background thread and speaks queued alerts through the same ARC connection.

This design ensures only one process ever speaks through ARC, preventing conflicts.

## Gemini integration (`jd_robot_system/gemini_brain.py`)

### Purpose

Gemini is used for conversational understanding and matching free-form requests to real robot actions. It is not used to directly drive the robot without verification.

### Request pipeline

- Gemini calls are made via plain HTTP requests to Google's `generateContent` endpoint.
- The code tries each model listed in `GEMINI_MODEL_CANDIDATES` in order.
- If a model returns 404, the next model is tried.
- Network errors and timeouts are retried a configurable number of times.

### Prompt format

`understand()` asks Gemini to reply in an exact two-line format:

- `REPLY: <spoken reply>`
- `MATCH: <category>|<name>`

`MATCH` must be one of `movement`, `sound`, `light`, or `NONE`.

This strict response format reduces ambiguity and makes it easier for the Python code to parse Gemini's output reliably.

### Other Gemini uses

- `assess_alert()` is used by `ambient_watcher.py` and `surveillance_watcher.py` to judge whether something observed in the scene should generate spoken feedback.
- `ambient_comment()` decides whether a scene change is worth commenting on at all, and produces tone-appropriate text.

## Vision pipeline (`vision_pipeline/01_full_pipeline.py`)

### Role

The vision pipeline is a pure sensor process:

- it connects to ARC,
- requests camera snapshots,
- runs object detection, pose tracking, and face recognition,
- derives simple scene state,
- writes it to `vision_pipeline/scene_state.json`.

It does not speak, execute robot actions, or depend on Gemini for the main scene state output.

### Camera snapshots

The pipeline uses ARC's `Camera Snapshot` skill to acquire frames and stores them temporarily in the user's Pictures folder. It reads the newest file, processes it, and removes older snapshots.

### Visual analysis

The pipeline combines:

- YOLO object detection for general objects,
- YOLO pose tracking for people and their track IDs,
- face recognition against `setup/known_encodings.pkl` to label known people,
- logic to infer whether a tracked person is holding a known object or sitting on furniture,
- posture estimation by comparing person bounding box height over time.

### Output format

It writes `vision_pipeline/scene_state.json` with the following structure:

- `timestamp` — when the scene state was produced,
- `objects_visible` — list of detected objects (excluding people),
- `people` — a dictionary keyed by tracker ID, each containing:
  - `name`,
  - `posture`,
  - `holding`,
  - `sitting_on`.

The file is written atomically using a temporary `.tmp` file followed by `os.replace(...)`.

### Snapshot requests

`surveillance_watcher.py` can request a saved picture by writing `vision_pipeline/snapshot_request.txt`. When the vision pipeline sees that file, it writes the current annotated frame into `jd_robot_system/snapshots/` and deletes the request.

## Scene context (`jd_robot_system/scene_context.py`)

`scene_context.py` reads `vision_pipeline/scene_state.json` and converts it into plain English for Gemini prompts.

- If the file does not exist or is older than 10 seconds, it returns `None`.
- If no people are visible, it returns `No one is currently visible.`
- Otherwise, it builds a concise description of each visible person, including posture, held object, and whether they are sitting on furniture.

This summary is optional and only used when the vision pipeline is actively producing fresh data.

## Local voice input (`jd_robot_system/voice_parakeet.py`)

### Mode

The repository supports local push-to-talk voice recognition as an alternative to typed input.

### How it works

- The user presses Enter to start recording.
- The code records audio from the default Windows microphone until a period of silence.
- It decodes the recording using `sherpa_onnx.OfflineRecognizer` with a Parakeet model.
- If speech is recognized, the transcribed text is returned and processed like a typed command.

### Required assets

This repository includes only `voice_model/parakeet/tokens.txt`. The actual Parakeet model `.onnx` files are not included and must be supplied separately:

- `encoder.int8.onnx`
- `decoder.int8.onnx`
- `joiner.int8.onnx`

### Speaking coordination

The voice module checks `tts.speaking_flag` and waits if JD is currently speaking, preventing JD from hearing its own speech.

## Auxiliary watcher processes

### Surveillance watcher

`jd_robot_system/surveillance_watcher.py` monitors `vision_pipeline/scene_state.json` for:

- unknown people,
- sensitive objects such as knives or scissors.

It requires a condition to persist across multiple polls before alerting and is rate-limited to avoid repeated alarms. When it decides an alert is needed, it:

- logs the event to `jd_robot_system/activity_log.txt`,
- requests a camera snapshot,
- queues a speech alert through `speech_queue.py`.

This watcher is fully offline and does not call Gemini or use the network.

### Ambient watcher

`jd_robot_system/ambient_watcher.py` monitors the same scene state for meaningful changes such as arrivals, departures, posture changes, and long idle states.

When it detects a change, it asks Gemini whether a short companion-style comment is appropriate. If Gemini produces a comment, it queues it through `speech_queue.py`.

Unlike the surveillance watcher, this component depends on Gemini/network availability and skips silently when Gemini is unavailable.

## Setup and configuration

### `jd_robot_system/config.py`

Key settings include:

- `ARC_HOST` and `ARC_PORT` — where ARC is listening for TCP commands.
- `GEMINI_API_KEY` — the Google Gemini key. The code first checks the `GEMINI_API_KEY` environment variable and falls back to the value in `config.py`.
- `GEMINI_MODEL_CANDIDATES` — fallback model names for Gemini.
- `SPEECH_POLL_INTERVAL` — if using ARC-based speech recognition instead of local voice.

### Face enrollment

`setup/enroll_faces.py` generates `known_encodings.pkl` from images in `setup/known_faces/`.

The vision pipeline uses that encoding file to identify known people in the camera feed.

### Dependencies

`requirements.txt` lists the Python packages required for the main code, vision pipeline, face recognition, and local Parakeet speech recognition.

The repository also relies on external model files:

- YOLO object and pose models for the vision pipeline,
- Parakeet `.onnx` files for local voice recognition,
- a valid Gemini API key for conversational features.

## Running the system

The cleanest setup is to run the vision pipeline, `main.py`, and optional watchers in separate processes. `start_jd.bat` is a convenience script for Windows users; it launches multiple Windows with the correct working directories.

If you run pieces manually, start `vision_pipeline/01_full_pipeline.py` first so scene state is available, then `jd_robot_system/main.py`, and optionally the watcher scripts.

## What this documentation emphasizes

- **Clear data boundaries**: the vision pipeline only writes sensor state; the main program only speaks and acts.
- **Single ARC speaker owner**: only `main.py` ever calls ARC `SayWait`.
- **Safe action whitelisting**: Gemini is used for understanding, but every robot action is validated against a known-safe list.
- **Optional features**: vision and Gemini are optional enhancements, not dependencies for the core typed-command path.

## Notes

- The repository does not include Synthiam ARC itself, nor the JD robot hardware.
- The Gemini key placeholder in `jd_robot_system/config.py` is not valid until replaced with a real key.
- The Parakeet `.onnx` voice model files are not included and must be obtained separately.
- There is no automated test suite included.
