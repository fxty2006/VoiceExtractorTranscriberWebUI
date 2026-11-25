@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ===================================================
echo [Voice Extractor ^& Transcriber WebUI] Dedicated venv Setup
echo ===================================================

set "PYTHON_BIN="
if exist "D:\Python312\python.exe" (
    set "PYTHON_BIN=D:\Python312\python.exe"
) else (
    for /f "delims=" %%i in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do (
        if not defined PYTHON_BIN set "PYTHON_BIN=%%i"
    )
)

if not defined PYTHON_BIN (
    for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
        if not defined PYTHON_BIN set "PYTHON_BIN=%%i"
    )
)

if not defined PYTHON_BIN (
    echo [ERROR] Python 3.12 ^(or compatible Python 3^) was not found.
    echo         Please install Python 3.10 - 3.12 and add it to PATH ^(or D:\Python312\python.exe^).
    pause
    exit /b 1
)

echo [INFO] Using Python: %PYTHON_BIN%

if not exist ".cache\pip" mkdir ".cache\pip"
if not exist ".cache\temp" mkdir ".cache\temp"
if not exist ".cache\tmp" mkdir ".cache\tmp"
if not exist ".cache\torch" mkdir ".cache\torch"
if not exist ".cache\huggingface" mkdir ".cache\huggingface"
if not exist "models" mkdir "models"
if not exist "models\mdx_net" mkdir "models\mdx_net"
if not exist "temp_preview" mkdir "temp_preview"
if not exist "outputs" mkdir "outputs"

set "PIP_CACHE_DIR=%~dp0.cache\pip"
set "TEMP=%~dp0.cache\temp"
set "TMP=%~dp0.cache\tmp"
set "TORCH_HOME=%~dp0.cache\torch"
set "HF_HOME=%~dp0.cache\huggingface"
set "XDG_CACHE_HOME=%~dp0.cache"

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating dedicated virtual environment in "%~dp0.venv" ...
    "%PYTHON_BIN%" -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment .venv.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Existing .venv found. Skipping creation.
)

echo.
echo [INFO] Installing dependencies from requirements.txt ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install --extra-index-url https://download.pytorch.org/whl/cu128 -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install packages from requirements.txt.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install nvidia-cublas-cu12 nvidia-cuda-runtime-cu12
".venv\Scripts\python.exe" -c "import pathlib, shutil; sp = pathlib.Path(r'.venv\Lib\site-packages'); ct2 = sp / 'ctranslate2'; [shutil.copy2(dll, ct2 / dll.name) for sub in ('nvidia/cublas/bin', 'nvidia/cuda_runtime/bin') if (sp / sub).exists() and ct2.exists() for dll in (sp / sub).glob('*.dll')]"

echo.
call :EnsureFfmpeg

echo.
set "MDX_MODEL_PATH=models\mdx_net\UVR-MDX-NET-Inst_HQ_5.onnx"
set "MDX_MODEL_PART=models\mdx_net\UVR-MDX-NET-Inst_HQ_5.onnx.part"
set "MDX_MODEL_URL=https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Inst_HQ_5.onnx"

if exist "%MDX_MODEL_PATH%" (
    echo [INFO] MDX-Net model already exists: %MDX_MODEL_PATH%
) else (
    echo [INFO] Downloading UVR-MDX-NET-Inst_HQ_5.onnx to %MDX_MODEL_PATH% ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%MDX_MODEL_URL%' -OutFile '%MDX_MODEL_PART%' -UseBasicParsing; if ((Get-Item '%MDX_MODEL_PART%').Length -lt 1000000) { throw 'Downloaded file is too small.' }; Move-Item -Force '%MDX_MODEL_PART%' '%MDX_MODEL_PATH%'; exit 0 } catch { if (Test-Path '%MDX_MODEL_PART%') { Remove-Item -Force '%MDX_MODEL_PART%' }; Write-Host $_.Exception.Message; exit 1 }"
    if errorlevel 1 (
        echo [WARNING] Failed to download UVR-MDX-NET-Inst_HQ_5.onnx automatically.
        echo           The official download URL may have changed or network access is unavailable.
        echo           Please place the model manually at:
        echo             %~dp0models\mdx_net\UVR-MDX-NET-Inst_HQ_5.onnx
        echo           See README.md for manual setup details, or use the built-in "hdemucs_high" model.
    ) else (
        echo [INFO] MDX-Net model downloaded successfully.
    )
)

echo.
echo [DONE] Setup completed. Run run_webui.bat to launch.
pause
exit /b 0

:EnsureFfmpeg
where ffmpeg >nul 2>&1
if not errorlevel 1 (
    echo [INFO] System FFmpeg detected in PATH. Skipping static-ffmpeg download.
    exit /b 0
)
".venv\Scripts\python.exe" -c "import os, pathlib; root = pathlib.Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Packages'; raise SystemExit(0 if (root.exists() and any(root.rglob('ffmpeg.exe'))) else 1)" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] WinGet FFmpeg detected. Skipping static-ffmpeg download.
    exit /b 0
)
echo [INFO] System FFmpeg not found. Preparing FFmpeg inside .venv via static-ffmpeg ...
".venv\Scripts\python.exe" -c "from static_ffmpeg import run as sf_run; sf_run.get_or_fetch_platform_executables_else_raise()"
if errorlevel 1 (
    echo [WARNING] Failed to prepare static-ffmpeg automatically.
    echo           Please install FFmpeg manually ^(e.g. winget install Gyan.FFmpeg^).
) else (
    echo [INFO] static-ffmpeg binaries are ready inside .venv.
)
exit /b 0