# JD Robot Cortex

## Summary

This repository contains a Python helper system for a JD humanoid robot that runs alongside Synthiam ARC. It is not ARC itself. The code is designed to:

- connect to ARC and send safe robot commands,
- speak replies through ARC's speech synthesis,
- accept typed commands or local push-to-talk voice commands,
- optionally use camera-derived vision context,
- optionally use Google Gemini for natural language understanding.

## Project structure

- `jd_robot_system/` - main robot control code, action execution, and speech interface.
- `vision_pipeline/` - optional vision processing and scene state generation.
- `setup/` - setup helpers such as face enrollment and GPU checks.
- `shared/` - shared helper modules used by multiple components.
- `voice_model/` - placeholder location for local speech model assets used by Parakeet.
- `start_jd.bat` - Windows helper script to launch the system.

The main entrypoint is `jd_robot_system/main.py`. It currently supports typed commands and local microphone voice input via `jd_robot_system/voice_parakeet.py`.

## Requirements

- Windows PC recommended for ARC and vision support.
- Python 3.10 or newer.
- Synthiam ARC installed and the JD robot project loaded.
- ARC TCP script server enabled on the host and port configured in `jd_robot_system/config.py`.
- If you want Gemini features, a valid Gemini API key.
- If you want local voice commands, you must provide the Parakeet model files in `voice_model/parakeet/`.

## Installation

1. Create and activate a Python virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. If you intend to use vision with an NVIDIA GPU, install the correct PyTorch wheels first using the command from https://pytorch.org. Example:

   ```powershell
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
   ```

3. Install the remaining dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

## Configuration

Open `jd_robot_system/config.py` and configure:

- `ARC_HOST` - the IP address where ARC is listening.
- `ARC_PORT` - the ARC TCP port (default 6666).
- `GEMINI_API_KEY` - your Gemini key, or set the environment variable `GEMINI_API_KEY`.

The code reads `GEMINI_API_KEY` from the environment first, then falls back to the value in `config.py`.

## Optional local voice model

Local push-to-talk voice recognition requires a Parakeet model asset folder at `voice_model/parakeet/`. The repository currently includes only `tokens.txt`. You must add the corresponding model files yourself:

- `encoder.int8.onnx`
- `decoder.int8.onnx`
- `joiner.int8.onnx`

If you do not provide these files, use typed command mode only.

## Running the system

Run the main program directly:

```powershell
cd jd_robot_system
python main.py
```

Or use `start_jd.bat` after editing the `ROOT` path at the top of the file to match your local checkout.

When `main.py` starts, choose:

- `t` to type commands,
- `v` to use local voice input via the microphone.

## Troubleshooting

- If ARC fails to connect, verify ARC is running, the JD project is loaded, the TCP server is enabled, and `ARC_HOST`/`ARC_PORT` are correct.
- If Gemini fails, verify your API key and run:

  ```powershell
  python -c "from jd_robot_system.gemini_brain import list_available_models; list_available_models()"
  ```

- If local voice doesn't work, confirm your microphone is available and `voice_model/parakeet/` contains the required `.onnx` files. You can test the setup with:

  ```powershell
  python jd_robot_system/test_parakeet.py
  ```

- If vision fails, run:

  ```powershell
  python vision_pipeline/00_baseline_gpu_test.py
  ```

- To refresh face recognition data, add photos to `setup/known_faces/` and run:

  ```powershell
  cd setup
  python enroll_faces.py
  ```

## Notes

- This repository is intended to be used alongside Synthiam ARC and a real JD robot.
- The local voice model files are not included in the repository.
- The Gemini API key placeholder in `jd_robot_system/config.py` will not work until replaced with a valid key.
- There is no automated test suite included in the repository.
- Do not put secret API keys into `config.py` if you are sharing this folder.
- This README is meant to explain what this folder contains and what it can do.
