@echo off
setlocal

SET "python_path=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\pythonw.exe"
SET "python_file=LINZ_WFS.py"
set logfile="%CD%\LINZ_WFS_last_run.log"

ECHO ========================================================
ECHO SCRIPT PATH = %CD%
ECHO.
ECHO python_path = %python_path%
ECHO python_file = %python_file%
ECHO arguments   = %*
ECHO ========================================================
ECHO.

"%python_path%" "%CD%\%python_file%" %* 1>> %logfile% 2>&1

endlocal