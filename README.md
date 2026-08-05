# JD Cortex

Perception, reasoning, and persistent memory for an EZ-Robot JD Humanoid, running on Synthiam ARC.

ARC drives the servos, speech, and onboard camera. JD Cortex is five Python processes that run beside it and do everything else.

A YOLO pipeline turns the camera feed into a structured scene description. A recorder distills that into a timestamped SQLite diary. A Gemini layer answers questions and issues actions, each checked against a fixed whitelist.

Memory is the distinguishing feature. Events are keyed by recognised identity, not by tracker id. So "who came in this morning" is answered from recorded data, by the same model and prompt that handle ordinary conversation.

---

## Quick start

Requires ARC running, the JD project loaded, and the **TCP Script Server** skill listening on port 6666.

```powershell
python -m venv robotenv
.\robotenv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:GEMINI_API_KEY = "your-key"

python run.py check      # what is ready, what is missing
python run.py            # start everything
```

`run.py check` reports every library, model file, key, and port before you commit to a session. Run it first.

---

## Features

**Perception** — object detection, pose, and face recognition, condensed into one `scene_state.json`.

**Memory** — arrivals, departures, and objects, stored as timestamped events in SQLite.

**Conversation** — Gemini handles dialogue and intent. Scene and diary enter the prompt as separate blocks.

**Speech** — transcription runs locally through Parakeet. No audio leaves the machine.

**Gesture control** — hand shapes from a webcam drive walking, turning, sitting, waving, standing.

**Autonomy** — a watcher alerts on unknown faces and sensitive objects. Ambient mode remarks unprompted.

**In-ARC panel** — a C# skill showing the live scene, with hold-to-talk and a gesture toggle.

---

## Architecture

```
camera ──► vision pipeline ──► scene_state.json ──┬──► witness recorder ──► diary
                                                  │
                                                  └──► brain ──► ARC ──► JD
                                                        ▲
                                      ARC panel ────────┘
```

| Process | Role |
| --- | --- |
| `vision_pipeline/01_full_pipeline.py` | detection, pose, faces → `scene_state.json` |
| `memory/witness_recorder.py` | scene file → diary events in SQLite |
| `jd_robot_system/main.py` | the brain: input, Gemini, validation, speech |
| `jd_robot_system/surveillance_watcher.py` | alerts on unknown people and objects |
| `jd_robot_system/ambient_watcher.py` | unprompted remarks about the scene |

Port **6666** is ARC's script server, where robot commands go. Port **5005** is the panel server inside `main.py`, where the ARC plugin connects.

`run.py` starts all five in dependency order and shuts them down together. Ctrl+C stops everything.

```powershell
python run.py --no-ambient   # skip unprompted remarks, save Gemini quota
python run.py --minimal      # brain and memory only, no vision
```

ARC's free tier allows one custom plugin slot. That constraint is why all the intelligence lives in Python and only simple results cross into ARC.

---

## Setup

**Python 3.10+ and Windows.** ARC and its plugin SDK are Windows-only.

**GPU optional.** The pipeline runs on CPU at a lower frame rate. Set `JD_OBJECT_MODEL` and `JD_POSE_MODEL` to the `yolov8n` variants to trade accuracy for speed. With an NVIDIA card, install PyTorch from pytorch.org before `requirements.txt`.

**MediaPipe is pinned to 0.10.21.** Later releases removed the API gesture control uses.

**Gemini quota is tight.** The free tier allows roughly twenty requests per day per model. Set `GEMINI_API_KEY_2` and `GEMINI_API_KEY_3` to give the system spare keys to rotate to.

### Optional assets

None of these ship with the repository. The system degrades gracefully without them.

| Asset | How to get it | Without it |
| --- | --- | --- |
| Face names | photos in `setup/known_faces/`, then `python enroll_faces.py` | diary works, nobody is named |
| Local voice | three `.onnx` files in `voice_model/parakeet/` | typed input only |
| YOLO weights | downloaded automatically on first run | — |

Photos and encodings are gitignored, and should stay that way.

---

## Data and privacy

The diary keeps fourteen days of events and prunes older ones at startup. `JD_DIARY_KEEP_DAYS` changes the window.

Four things are deliberately untracked: the diary database, enrolled face photos and their encodings, captured snapshots, and model weights. This repository holds source, not runtime data and not anyone's photograph.

---

## The Memory panel

A C# behaviour skill in `memory/plugin/`. Open the `.csproj` in Visual Studio and build — the DLL lands in ARC's plugin folder. Then in ARC: **Project → Add Skill → Beta → Memory**.

It shows a connection light, a live card of what JD sees, example questions, one input box for both memory questions and commands, hold-to-talk, and a gesture toggle. It asks Python for the bridge folder path on connection, so nothing needs configuring by hand.

| Gesture | Action |
| --- | --- |
| fist | forward |
| open hand | stop |
| index left / right | turn |
| index down | sit |
| peace sign | wave |
| three fingers | stand |
| index + pinky | pushups |

Gestures are read from the laptop webcam, not JD's camera. JD's camera moves when JD does, so a forward gesture would shake the view, lose the hand, and trip the safety stop.

---

## Troubleshooting

Run `python run.py check` first. It answers most of these.

| Symptom | Cause |
| --- | --- |
| ARC won't connect | TCP Script Server skill not running on 6666 |
| Gemini fails every call | usually quota, not a bad key — watch the panel counter |
| Nobody gets named | `known_encodings.pkl` missing; run enrollment |
| Voice input does nothing | `.onnx` files missing, or microphone unavailable |
| Panel connects, scene card empty | vision pipeline isn't writing `scene_state.json` |
| Nothing is remembered | witness recorder process not running |

Both memory components can be exercised with no camera attached:

```powershell
python memory\witness_recorder.py selftest
python memory\gesture_control.py selftest
```

There is no automated test suite. These self-tests are the substitute.

To see which Gemini models a key can currently reach:

```powershell
cd jd_robot_system
python -c "from gemini_brain import list_available_models; list_available_models()"
```

---

## Credits

**Aima Naqvi** — YOLO vision pipeline, Gemini conversation and intent matching, whitelisted action execution, unknown-face and sensitive-object surveillance, ambient mode.

**Bushra Ushaq** — SQLite witness diary and recorder, ARC Memory panel (C# skill and Python server), MediaPipe gesture control, unified launcher