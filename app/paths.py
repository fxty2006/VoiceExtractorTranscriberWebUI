"""
パス管理およびCドライブ書き込み遮断モジュール (app/paths.py)
すべてのキャッシュ・一時ファイル・モデル保存先・出力先をDドライブのプロジェクト配下へ固定する。
"""

import os
import shutil
from pathlib import Path
from typing import Optional, Set

BASE_DIR: Path = Path(__file__).resolve().parent.parent

CACHE_DIR: Path = BASE_DIR / ".cache"
PIP_CACHE_DIR: Path = CACHE_DIR / "pip"
TORCH_CACHE_DIR: Path = CACHE_DIR / "torch"
HF_CACHE_DIR: Path = CACHE_DIR / "huggingface"
TEMP_WORK_DIR: Path = CACHE_DIR / "tmp"

MODELS_DIR: Path = BASE_DIR / "models"
TEMP_PREVIEW_DIR: Path = BASE_DIR / "temp_preview"
DEFAULT_OUTPUT_DIR: Path = BASE_DIR / "outputs"
STATIC_DIR: Path = BASE_DIR / "static"

CONFIG_PATH: Path = BASE_DIR / "config.json"
CONFIG_EXAMPLE_PATH: Path = BASE_DIR / "config.example.json"

# 既存のDドライブ内ローカルWhisperモデル（存在すればオフラインで利用可能）
EXTERNAL_LOCAL_WHISPER_DIR: Path = Path(r"D:\ComfyUI\models\faster-whisper\large-v3-turbo-local")
EXTERNAL_LOCAL_OPENAI_WHISPER_PT: Path = Path(r"D:\ComfyUI\cache\whisper\large-v3-turbo.pt")

VIDEO_EXTENSIONS: Set[str] = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
AUDIO_EXTENSIONS: Set[str] = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
ALLOWED_EXTENSIONS: Set[str] = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


def ensure_directories() -> None:
    """必要な作業・キャッシュディレクトリをDドライブ配下に作成する。"""
    for directory in (
        CACHE_DIR,
        PIP_CACHE_DIR,
        TORCH_CACHE_DIR,
        HF_CACHE_DIR,
        HF_CACHE_DIR / "hub",
        TEMP_WORK_DIR,
        MODELS_DIR,
        TEMP_PREVIEW_DIR,
        DEFAULT_OUTPUT_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def enforce_d_drive_env() -> None:
    """Cドライブへのキャッシュ・一時ファイル流出を防ぐため環境変数をDドライブ配下に固定する。"""
    ensure_directories()
    os.environ["PIP_CACHE_DIR"] = str(PIP_CACHE_DIR)
    os.environ["TORCH_HOME"] = str(TORCH_CACHE_DIR)
    os.environ["HF_HOME"] = str(HF_CACHE_DIR)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_CACHE_DIR / "hub")
    os.environ["XDG_CACHE_HOME"] = str(CACHE_DIR)
    os.environ["TEMP"] = str(TEMP_WORK_DIR)
    os.environ["TMP"] = str(TEMP_WORK_DIR)
    os.environ["GRADIO_TEMP_DIR"] = str(TEMP_WORK_DIR)


def _find_winget_binary(exe_name: str) -> Optional[str]:
    """PATH未登録環境向けに既知のWinGetパッケージ配下から実行ファイルを探索する。"""
    winget_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if not winget_root.exists():
        return None
    for match in winget_root.rglob(exe_name):
        if match.is_file():
            return str(match)
    return None


def _find_static_ffmpeg_binary(exe_name: str) -> Optional[str]:
    """システムにFFmpegが無い環境向けに、専用.venv内のstatic-ffmpegバイナリを解決する。"""
    try:
        from static_ffmpeg import run as sf_run  # type: ignore

        ffmpeg_exe, ffprobe_exe = sf_run.get_or_fetch_platform_executables_else_raise()
        target = ffprobe_exe if "ffprobe" in exe_name.lower() else ffmpeg_exe
        if target and Path(target).is_file():
            return str(target)
    except Exception:
        pass
    return None


def resolve_ffmpeg() -> str:
    """ffmpeg実行ファイルのパスを解決する。見つからない場合は RuntimeError を送出する。"""
    found = shutil.which("ffmpeg")
    if found:
        return found
    winget_found = _find_winget_binary("ffmpeg.exe")
    if winget_found:
        return winget_found
    static_found = _find_static_ffmpeg_binary("ffmpeg.exe")
    if static_found:
        return static_found
    raise RuntimeError("ffmpeg が見つかりません。システムPATHまたは導入状態を確認してください。")


def resolve_ffprobe() -> Optional[str]:
    """ffprobe実行ファイルのパスを解決する。見つからない場合は None を返す。"""
    found = shutil.which("ffprobe")
    if found:
        return found
    try:
        ffmpeg_path = Path(resolve_ffmpeg())
        sibling = ffmpeg_path.with_name("ffprobe.exe")
        if sibling.exists():
            return str(sibling)
    except RuntimeError:
        pass
    winget_found = _find_winget_binary("ffprobe.exe")
    if winget_found:
        return winget_found
    return _find_static_ffmpeg_binary("ffprobe.exe")


def is_video_extension(filename: str) -> bool:
    """拡張子が動画形式かどうかを判定する。"""
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS


def is_supported_extension(filename: str) -> bool:
    """入力対応拡張子かどうかを判定する。"""
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS