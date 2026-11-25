@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ===================================================
echo [Voice Extractor ^& Transcriber WebUI] Updater
echo ===================================================

if not exist ".git" (
    echo [ERROR] .git folder was not found in "%~dp0".
    echo         This updater requires a Git-cloned repository.
    echo         If you downloaded a ZIP archive, please download the latest release manually
    echo         or re-install via "git clone".
    pause
    exit /b 1
)

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] "git" command was not found in PATH.
    echo         Please install Git for Windows first.
    pause
    exit /b 1
)

echo [INFO] Pulling latest updates from remote repository ...
git pull
if errorlevel 1 (
    echo [ERROR] "git pull" failed.
    echo         Please check your network connection or resolve any local file changes.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    echo.
    echo [INFO] Syncing Python packages in .venv ...
    if not exist ".cache\pip" mkdir ".cache\pip"
    if not exist ".cache\temp" mkdir ".cache\temp"
    if not exist ".cache\tmp" mkdir ".cache\tmp"
    if not exist ".cache\torch" mkdir ".cache\torch"
    if not exist ".cache\huggingface" mkdir ".cache\huggingface"

    set "PIP_CACHE_DIR=%~dp0.cache\pip"
    set "TEMP=%~dp0.cache\temp"
    set "TMP=%~dp0.cache\tmp"
    set "TORCH_HOME=%~dp0.cache\torch"
    set "HF_HOME=%~dp0.cache\huggingface"
    set "XDG_CACHE_HOME=%~dp0.cache"

    ".venv\Scripts\python.exe" -m pip install --extra-index-url https://download.pytorch.org/whl/cu128 -r requirements.txt
    if errorlevel 1 (
        echo [WARNING] Package sync encountered an error. You may retry setup_venv.bat if needed.
    ) else (
        call :CheckStaticFfmpeg
    )
) else (
    echo.
    echo [INFO] .venv was not found yet. Run setup_venv.bat to build the environment.
)

echo.
echo [DONE] Update completed.
pause
exit /b 0

:CheckStaticFfmpeg
where ffmpeg >nul 2>&1
if not errorlevel 1 exit /b 0
".venv\Scripts\python.exe" -c "import os, pathlib; root = pathlib.Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Packages'; raise SystemExit(0 if (root.exists() and any(root.rglob('ffmpeg.exe'))) else 1)" >nul 2>&1
if not errorlevel 1 exit /b 0

echo [INFO] System FFmpeg not found. Checking static-ffmpeg binaries in .venv ...
".venv\Scripts\python.exe" -c "from static_ffmpeg import run as sf_run; sf_run.get_or_fetch_platform_executables_else_raise()"
if errorlevel 1 (
    echo [WARNING] Could not fetch static-ffmpeg automatically. Please install FFmpeg or check network access.
)
exit /b 0
