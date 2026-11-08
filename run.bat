@echo off
setlocal
rem Starts G-code Shifter with the global Python. Installs PySide6 on first run if missing.
cd /d "%~dp0" || exit /b 1
where python >nul 2>nul || (echo Python was not found on PATH. Install Python 3.10+ from python.org. & pause & exit /b 1)
python -c "import PySide6" 2>nul || (
    echo Installing PySide6...
    python -m pip install -r requirements.txt || (echo Installing PySide6 failed. & pause & exit /b 1)
)
rem Use pythonw.exe from the same Python install so no console window stays open.
set "PYW="
for /f "delims=" %%i in ('python -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"') do set "PYW=%%i"
if exist "%PYW%" (start "" "%PYW%" gcode_shifter.py %*) else (python gcode_shifter.py %*)
