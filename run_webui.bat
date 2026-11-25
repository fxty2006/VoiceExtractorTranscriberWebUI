@echo off
cd /d "%~dp0"

if not exist ".cache\pip" mkdir ".cache\pip"
if not exist ".cache\temp" mkdir ".cache\temp"
if not exist ".cache\torch" mkdir ".cache\torch"
if not exist ".cache\huggingface" mkdir ".cache\huggingface"
if not exist "models" mkdir "models"
if not exist "temp_preview" mkdir "temp_preview"
if not exist "outputs" mkdir "outputs"

set PIP_CACHE_DIR=%~dp0.cache\pip
set TEMP=%~dp0.cache\temp
set TMP=%~dp0.cache\temp
set TORCH_HOME=%~dp0.cache\torch
set HF_HOME=%~dp0.cache\huggingface
set XDG_CACHE_HOME=%~dp0.cache

echo ===================================================
echo [Voice Extractor ^& Transcriber WebUI] Starting Server...
echo - Base Dir   : %~dp0
echo - Model Cache: %TORCH_HOME%
echo - Output Dir : %~dp0outputs
echo - WebUI URL  : http://127.0.0.1:7865
echo ===================================================

start "" "http://127.0.0.1:7865"
".venv\Scripts\python.exe" server.py --host 127.0.0.1 --port 7865
pause
