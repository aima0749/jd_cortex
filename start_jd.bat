@echo off
REM JD Full System Launcher
REM Starts the vision pipeline, witness recorder, command system,
REM surveillance watcher, and ambient watcher - each in its own window,
REM with the virtual environment activated.
REM Adjust ROOT below to match your own folder.

set ROOT=C:\Users\PC\Documents\JD_robot

echo Starting vision pipeline...
start "JD Vision Pipeline" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\vision_pipeline && python 01_full_pipeline.py"

echo Starting witness recorder...
start "JD Witness Recorder" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT% && python memory\witness_recorder.py"

REM give the vision pipeline a few seconds to load its models and start
REM writing scene_state.json before anything starts reading it
timeout /t 8 /nobreak

echo Starting command system...
start "JD Command System" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\jd_robot_system && python main.py"

echo Starting surveillance watcher...
start "JD Surveillance Watcher" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\jd_robot_system && python surveillance_watcher.py"

echo Starting ambient watcher...
start "JD Ambient Watcher" cmd /k "cd /d %ROOT%\jd_env\Scripts && call activate && cd /d %ROOT%\jd_robot_system && python ambient_watcher.py"

echo All five started in separate windows.