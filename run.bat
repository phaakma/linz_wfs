@echo off
setlocal
cls

SET "python_path=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\pythonw.exe"
SET "python_file=LINZ_WFS.py"

rem Define the path to the temporary log file
set tempfile="%CD%\logs\temp_output.log"
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

"%python_path%" "%CD%\%python_file%" %* 1> "%CD%\logs\%python_file%_last_run.log" 2>&1

endlocal