@echo off
echo =========================================
echo   TS24 Puccetti -- 2D Data Import
echo   (Incremental mode -- cache backed)
echo =========================================
echo.

set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%..
set EXCEL=%ROOT_DIR%\02_DATABASE\TS24 DB Master.xlsx
set CACHE=%ROOT_DIR%\02_DATABASE\all_sessions.json

echo Excel : %EXCEL%
echo Cache : %CACHE%
echo.

echo New round data folder path (drag and drop or type full path).
echo Leave blank to rebuild Excel from cache only:
echo.
set /p NEW_DATA_DIR="Folder: "

if "%NEW_DATA_DIR%"=="" (
    echo.
    echo No folder specified -- rebuilding Excel from cache...
    set SCAN_PATH=NONE
) else if not exist "%NEW_DATA_DIR%" (
    echo.
    echo WARNING: Folder not found: %NEW_DATA_DIR%
    echo Rebuilding Excel from cache only...
    set SCAN_PATH=NONE
) else (
    echo.
    echo Scanning: %NEW_DATA_DIR%
    set SCAN_PATH=%NEW_DATA_DIR%
)

echo.
python "%SCRIPT_DIR%parse_2d_to_excel.py" "%SCAN_PATH%" "%EXCEL%" "%CACHE%"

echo.
pause
