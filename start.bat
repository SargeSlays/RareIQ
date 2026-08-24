@echo off
setlocal
cd /d "%~dp0"
set PIP_DISABLE_PIP_VERSION_CHECK=1

if not exist .venv\Scripts\python.exe (
    py -3.13 -m venv .venv
    if errorlevel 1 goto :setup_failed
)

call .venv\Scripts\activate
if errorlevel 1 goto :setup_failed

python -m pip install -r requirements.txt
if errorlevel 1 goto :setup_failed

python -B app.py
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" echo RareIQ exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%

:setup_failed
echo.
echo RareIQ environment setup failed.
pause
exit /b 1
