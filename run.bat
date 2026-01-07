@echo off
setlocal

set ROOT=%~dp0
set VENV=%ROOT%\.venv
set PY=%VENV%\Scripts\python.exe

where python >nul 2>&1
if errorlevel 1 goto no_python

if not exist "%PY%" (
  python -m venv "%VENV%"
)
if not exist "%PY%" (
  if exist "C:\Program Files\Python311\python.exe" (
    "C:\Program Files\Python311\python.exe" -m venv "%VENV%"
  )
)
if not exist "%PY%" goto venv_failed

"%PY%" -m pip install -U pip >nul 2>&1
if exist "%ROOT%requirements.txt" (
  echo Installing dependencies...
  "%PY%" -m pip install -r "%ROOT%requirements.txt"
)

set APP_MODE=gui
"%PY%" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto tk_missing

echo Starting app...
if exist "L:\data" goto has_data_root
set CW_DATA_ROOT=%ROOT%data
goto after_data_root
:has_data_root
set CW_DATA_ROOT=L:\data
:after_data_root
REM If you want to move database file too, set CW_DB_PATH (optional)
REM set CW_DB_PATH=L:\data\image_classifier.db
"%PY%" "%ROOT%main.py"

if errorlevel 1 goto app_crashed

endlocal
goto :eof

:no_python
echo Python not found. Please install Python 3.8+
pause
exit /b 1

:venv_failed
echo Failed to create venv: %VENV%
pause
exit /b 1

:tk_missing
echo Tkinter not installed. Please install Python 3.11.9 with Tcl/Tk
pause
exit /b 1

:app_crashed
echo(
echo App crashed. Please check the error above.
pause
