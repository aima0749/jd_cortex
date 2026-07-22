# ProjectMoveMint - JD Robot System

## Non-technical summary

This folder contains a Python project that helps control a JD humanoid robot using the ARC software. It is not the robot itself. It is a set of programs that:

- connect to the robot control software (ARC),
- send the robot safe commands,
- speak messages through the robot,
- uses a camera system to understand the scene,
- uses Google Gemini to interpret natural language commands.

If you are not a programmer, the important part is that this project is a helper system for the robot. It requires ARC and a working robot setup to do anything useful.

## Technical summary

This folder contains:

- `jd_robot_system/` - the main robot control code.
- `vision_pipeline/` - optional vision processing and scene state output.
- `setup/` - setup helpers like GPU checks and face enrollment.
- `shared/` - shared utilities and diagnostics tools.
- `start_jd.bat` - a Windows helper script to launch the main program.

The main program is `jd_robot_system/main.py`. It can accept typed commands or voice commands from ARC. It uses `jd_robot_system/known_actions.py` to know what actions are safe for the robot.

`jd_robot_system/config.py` contains the settings. You must update it with your ARC host, port, and your Gemini API key before using the system.

## What works in this folder

- The main Python program can run and send commands to ARC if ARC is available.
- The project can speak through ARC using `jd_robot_system/tts.py`.
- Typed commands are supported.
- Voice command mode is supported if ARC speech recognition is enabled.
- Google Gemini support is available if a valid API key is set.
- The vision pipeline files are present, though vision is optional and depends on the camera setup and GPU.
- There are diagnostics tools in `shared/diagnostics/` for checking the ARC connection.

## What is not ready or may fail

- The default `GEMINI_API_KEY` in `jd_robot_system/config.py` is not valid. Gemini features will not work until you add a real key.
- Gemini model names may change over time. If Gemini stops working, the code may need model updates.
- Voice mode only works if ARC speech recognition is active and configured.
- The vision pipeline only works if the vision code is running and `scene_state.json` is kept current.
- This folder has not been fully tested on Linux or macOS.
- There is no automated test suite included.

## Quick start

1. Install Python 3.8 or higher.
2. Install required packages:

   ```powershell
   pip install google-generativeai requests ultralytics opencv-python numpy Pillow face_recognition pydub
   ```

3. Edit `jd_robot_system/config.py` and set:
   - `GEMINI_API_KEY` to your real Google Gemini API key.
   - `ARC_HOST` and `ARC_PORT` to the address where ARC is running.

4. Start ARC and load the JD robot project.
5. Run the main program from this folder:

   ```powershell
   python jd_robot_system\main.py
   ```

   Or use the Windows helper:

   ```powershell
   .\start_jd.bat
   ```

## Troubleshooting

- If ARC does not connect, run `python shared/diagnostics/arc_port_scanner.py`.
- If Gemini does not work, verify `GEMINI_API_KEY` and run:

  ```powershell
  python -c "from jd_robot_system.gemini_brain import list_available_models; list_available_models()"
  ```

- If vision does not work, run `python vision_pipeline/00_baseline_gpu_test.py`.
- If you need to update face data, run `python setup/enroll_faces.py`.

## Notes

- Do not put secret API keys into `config.py` if you are sharing this folder.
- This README is meant to explain what this folder contains and what it can do.
