@echo off
REM JD Full System Launcher
REM Starts both the vision pipeline and the command/voice system,
REM each in its own window, with the virtual environment activated.
REM Adjust the paths below if your folder names differ.

set ROOT=C:\Users\PC\Documents\JD_robot

echo Starting vision pipeline...
start "JD Vision Pipeline" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\vision_pipeline && python 01_full_pipeline.py"

REM give the vision pipeline a few seconds to load its models and start
REM writing scene_state.json before the command system starts checking it
timeout /t 8 /nobreak

echo Starting command system...
start "JD Command System" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\jd_robot_system && python main.py"

echo Both started in separate windows.