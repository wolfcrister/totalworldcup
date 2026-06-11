@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" play_game.py --single
) else (
  python play_game.py --single
)
