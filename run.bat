@echo off
setlocal

SET "python_path=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\pythonw.exe"
SET "python_file=LINZ_WFS.py"

rem Define the path to the log file
set logfile="%CD%\logs\%python_file%_last_run.log"

rem Delete the existing log file if it exists
if exist %logfile% del %logfile%

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

"%python_path%" "%CD%\%python_file%" %* 1> %logfile% 2>&1

endlocal