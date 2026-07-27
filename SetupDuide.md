# JD Robot — Setup Guide

This sets up JD's full software system: vision (camera/object/face detection),
voice input (local speech-to-text), Gemini-powered understanding, and speech
output through JD's onboard speaker.

---

## 1. Requirements

- Windows PC with an NVIDIA GPU (recommended — CPU works but is much slower for vision)
- Python 3.10 or newer
- Synthiam ARC installed, with JD's project loaded and the physical EZ-B v4 board available
- Internet connection (for initial setup and Gemini API calls)

---

## 2. Get the code

```powershell
git clone https://github.com/aima0749/jd_cortex.git
cd jd_cortex
```

---

## 3. Set up the Python environment

```powershell
python -m venv jd_env
.\jd_env\Scripts\Activate.ps1
```

Install GPU-enabled PyTorch **first** (check [pytorch.org](https://pytorch.org) for the exact command matching your GPU's CUDA version — example below):
```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

Then install everything else:
```powershell
pip install -r requirements.txt
```

---

## 4. Download the local speech-to-text model

One-time download (~600MB), no manual steps needed:
```powershell
python setup_voice_model.py
```

---

## 5. Enroll known faces (optional, for face recognition)

1. Put clear photos of each person into `setup/known_faces/` (e.g. `alex.jpg`)
2. Run:
   ```powershell
   cd setup
   python enroll_faces.py
   cd ..
   ```
This generates `known_encodings.pkl` locally — it's personal data and is **not** included in the repo, so this step must be done fresh on each machine.

---

## 6. Set your Gemini API key

1. Get a free key: https://aistudio.google.com/apikey
2. Open `jd_robot_system/config.py`
3. Replace:
   ```python
   GEMINI_API_KEY = "PUT_YOUR_KEY_HERE"
   ```
   with the real key.

---

## 7. Set up ARC

1. Open Synthiam ARC and load JD's project.
2. **Add the Speech Synthesis skill** (required for JD to actually speak):
   `Project → Add Robot Skill → Audio → Speech Synthesis`
3. **Enable the TCP script server**:
   `Options → TCP Server` → check *Enable Server for EZ_B Board 0*, port `6666`.
4. **Connect to the physical EZ-B v4 board**: in the Connection panel, click *Connect* and confirm it turns green (this is separate from the TCP server above).

---

## 8. Run everything

Easiest way — starts both the vision pipeline and the command system together:
```powershell
start_jd.bat
```

Or run them separately, in two terminals (vision pipeline first, give it ~10 seconds to load before starting the second):
```powershell
cd vision_pipeline
python 01_full_pipeline.py
```
```powershell
cd jd_robot_system
python main.py
```

When `main.py` asks for input mode, choose:
- **`t`** — type commands
- **`v`** — speak commands (press Enter, then talk — local, offline, no internet needed for this part)

---

## Troubleshooting

- **JD doesn't speak** — confirm the Speech Synthesis skill (step 7.2) is added and the EZ-B board shows connected/green (step 7.4).
- **Gemini errors about a model** — run this diagnostic to see what's currently available:
  ```powershell
  python -c "from gemini_brain import list_available_models; list_available_models()"
  ```
  Update `GEMINI_MODEL_CANDIDATES` in `config.py` if needed.
- **Face recognition shows "unknown" for everyone** — repeat step 5 with clearer, well-lit photos.