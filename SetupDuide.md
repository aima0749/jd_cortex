# JD Robot — Setup Guide

This guide helps you set up JD's Python helper system, including vision support, local voice input, Gemini-powered understanding, and speech output through ARC.

---

## 1. Requirements

- Windows PC with an NVIDIA GPU recommended for vision performance.
- Python 3.10 or newer.
- Synthiam ARC installed with the JD project loaded.
- Internet connection for initial dependency installation and optional Gemini API calls.

---

## 2. Get the code

```powershell
git clone https://github.com/aima0749/jd_cortex.git
cd jd_cortex
```

---

## 3. Create the Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If you want GPU support for vision, install the correct PyTorch wheel first from https://pytorch.org. Example:

```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

Then install the repository dependencies:

```powershell
pip install -r requirements.txt
```

---

## 4. Local voice model

Local voice recognition uses a Parakeet model folder at `voice_model/parakeet/`.

The repository currently includes only `tokens.txt`; the `.onnx` model files are not included. To use voice mode, add the following files to `voice_model/parakeet/`:

- `encoder.int8.onnx`
- `decoder.int8.onnx`
- `joiner.int8.onnx`

If you do not have these model files, use typed command mode instead.

---

## 5. Enroll known faces (optional)

1. Put clear photos of each person into `setup/known_faces/` (for example: `alex.jpg`).
2. Run:

   ```powershell
   cd setup
   python enroll_faces.py
   cd ..
   ```

This creates `known_encodings.pkl` locally. It is personal data and is not stored in the repository.

---

## 6. Set your Gemini API key

1. Get a key from https://aistudio.google.com/apikey.
2. Open `jd_robot_system/config.py`.
3. Set the API key in `GEMINI_API_KEY`, or set the environment variable `GEMINI_API_KEY` before running.

---

## 7. Set up ARC

1. Open Synthiam ARC and load the JD project.
2. Add the Speech Synthesis skill: `Project → Add Robot Skill → Audio → Speech Synthesis`.
3. Enable the TCP script server: `Options → TCP Server` → check *Enable Server for EZ_B Board 0* on port `6666`.
4. Connect the EZ-B v4 board so the robot is ready to receive commands.

---

## 8. Run the system

The easiest way is to use `start_jd.bat`, but first edit the `ROOT` variable at the top of the file to point to your checkout folder.

```powershell
start_jd.bat
```

Or run the components manually:

```powershell
cd vision_pipeline
python 01_full_pipeline.py
```

```powershell
cd jd_robot_system
python main.py
```

When the program asks for input mode, choose:

- `t` — type commands.
- `v` — local voice commands (press Enter, then speak).

---

## Troubleshooting

- **JD does not speak** — make sure ARC has the Speech Synthesis skill and the TCP server is enabled.
- **Gemini problems** — verify your API key and try:

  ```powershell
  python -c "from jd_robot_system.gemini_brain import list_available_models; list_available_models()"
  ```

- **Local voice input does not work** — confirm your mic works and that `voice_model/parakeet/` contains the required Parakeet `.onnx` files.
- **Vision fails to start** — run:

  ```powershell
  python vision_pipeline/00_baseline_gpu_test.py
  ```

- **Face recognition is not accurate** — repeat enrollment with clear, well-lit photos.
