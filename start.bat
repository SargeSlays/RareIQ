@echo off
setlocal
if not exist .venv (
    py -3.13 -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo RareIQ dependency installation failed.
    pause
    exit /b 1
)
python app.py
pause
