@echo off
rem Starts the G-code Shifter. First run creates .venv and installs dependencies.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
".venv\Scripts\python.exe" -m streamlit run gcode_processor.py
goto :eof
:error
echo Setup failed.
pause
