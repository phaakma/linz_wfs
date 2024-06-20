@echo off
cls

SET "python_path=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\pythonw.exe"
SET "python_file=LINZ_WFS.py"

ECHO ========================================================
ECHO SCRIPT PATH = %CD%
ECHO.
ECHO python_path = %python_path%
ECHO python_file = %python_file%
ECHO arguments   = %*
ECHO ========================================================
ECHO.

REM Ensure logs folder exists
if not exist "%CD%\logs" mkdir "%CD%\logs"

"%python_path%" "%CD%\%python_file%" %* 1> "%CD%\logs\%python_file%_last_run.log" 2>&1
