# ProjectMoveMint Documentation

This document describes the features and purpose of the ProjectMoveMint robot control project in this folder.

## Purpose

ProjectMoveMint is a Python-based helper system for a JD humanoid robot that works with the ARC robot control framework.

It is designed to:

- connect to ARC and send robot commands safely,
- speak messages through the robot using ARC text-to-speech,
- allow typed and optional voice command control,
- optionally use vision scene data to improve command context,
- optionally use Google Gemini for natural language interpretation.

## Main features

### 1. Robot command control

- The main control logic is in `jd_robot_system/main.py`.
- Commands are translated into a safe set of actions defined in `jd_robot_system/known_actions.py`.
- The system sends commands to ARC using `jd_robot_system/arc_connection.py`.
- Both movement and sound/light actions can be triggered if they are present in the approved action list.

### 2. Text-to-speech

- `jd_robot_system/tts.py` sends speech commands to ARC.
- This lets the robot speak responses and status updates.

### 3. Typed and voice command modes

- Typed command mode works directly from the console.
- Voice command mode uses ARC's built-in speech recognition through `jd_robot_system/speech_input.py`.
- Voice mode depends on ARC speech recognition being enabled inside the ARC project.

### 4. Safe action validation

- The project uses a local list of allowed robot actions in `jd_robot_system/known_actions.py`.
- Any action suggestion from Gemini or voice input still passes through local validation before being sent to the robot.
- This prevents the robot from executing actions that are not explicitly approved.

### 5. Optional Gemini natural language support

- `jd_robot_system/gemini_brain.py` is responsible for calling Google Gemini.
- Gemini is used only to interpret natural language commands and suggest the closest known action.
- Gemini support requires a valid API key in `jd_robot_system/config.py`.

### 6. Optional vision context support

- `jd_robot_system/scene_context.py` reads scene state data from `vision_pipeline/scene_state.json`.
- If the vision pipeline is running and producing fresh data, that information is included in Gemini prompts.
- This allows the robot to respond with better context about the current environment.

### 7. Vision pipeline files

- The folder `vision_pipeline/` contains vision processing scripts and model files.
- `vision_pipeline/01_full_pipeline.py` is the main vision processing script.
- `vision_pipeline/00_baseline_gpu_test.py` checks whether the GPU environment is ready.
- Vision support is optional and may require a GPU and the appropriate dependencies.

### 8. Witness memory

- `memory/witness_recorder.py` runs alongside the vision pipeline and turns raw sightings from `scene_state.json` into debounced diary events (arrivals, departures with duration, held objects, furniture, objects coming into view).
- Events are stored in `memory/witness_store.py`'s SQLite diary (`memory/witness_diary.sqlite3`, WAL mode, safe across processes).
- `jd_robot_system/memory_context.py` formats the diary into a compact text block that `main.py` adds to the single Gemini prompt, so the same brain that handles commands also answers questions about what JD has seen. There is no second answering path.
- With `JD_ANNOUNCE=on` the recorder queues spoken arrival announcements through the existing speech queue; it never opens its own ARC connection.

### 9. ARC panel (Memory plugin)

The ARC custom plugin in `memory/plugin/` gives one clear screen:
what JD sees, a box to ask or command anything, clickable example
questions, hold-to-talk speech, and a hand-gesture switch. It connects
to `main.py` on port 5005 (`jd_robot_system/panel_server.py`), so panel
input flows through the identical path as typed and spoken commands.
`jd_robot_system/panel_listen.py` records while the button is held and
transcribes offline with the shared Parakeet model;
`memory/gesture_control.py` runs as its own process, reading the frames
the plugin writes and sending Auto Position actions straight to ARC,
with a safety stop if the hand disappears mid-walk.

### 10. Setup and diagnostics

- `setup/` contains initial setup helpers including face enrollment and GPU checks.
- `shared/diagnostics/` contains tools for verifying ARC connectivity and robot communication.

## What you need before running

- Python 3.8 or higher.
- ARC software installed and running.
- A JD robot project loaded in ARC.
- `jd_robot_system/config.py` configured with the correct ARC address and a valid Gemini API key if you want Gemini features.

## Notes

- This folder does not include the ARC software itself.
- It is intended to be used alongside ARC and a real robot.
- The default Gemini configuration in `jd_robot_system/config.py` is a placeholder; replace it before using Gemini.
- There is no automatic test suite in this folder.
