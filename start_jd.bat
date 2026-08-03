@echo off
REM JD Full System Launcher
REM Starts vision pipeline, command system, surveillance watcher, and the
REM new ambient watcher, each in its own window, venv activated.
REM Adjust the paths below if your folder names differ.

set ROOT=C:\Users\PC\Documents\JD_robot

echo Starting vision pipeline...
start "JD Vision Pipeline" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\vision_pipeline && python 01_full_pipeline.py"

echo Starting command system...
start "JD Command System" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\jd_robot_system && python main.py"

echo Starting surveillance watcher...
start "JD Surveillance Watcher" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\jd_robot_system && python surveillance_watcher.py"

echo Starting ambient watcher...
start "JD Ambient Watcher" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\jd_robot_system && python ambient_watcher.py"

echo All four started in separate windows.