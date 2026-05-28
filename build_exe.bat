@echo off
REM Build script: installs deps and builds a single EXE using PyInstaller
setlocal
set PYTHON=python
if exist ".venv\Scripts\python.exe" set PYTHON=.venv\Scripts\python.exe

"%PYTHON%" -m pip install --upgrade pip
"%PYTHON%" -m pip install -r requirements.txt
"%PYTHON%" -m PyInstaller --noconfirm BeatsFinder.spec

echo Build finished. Check the "dist" folder for BeatsFinder.exe
pause
