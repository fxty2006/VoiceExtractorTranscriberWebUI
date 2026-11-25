"""
出力パス・プリフィックス展開モジュール (app/prefix_resolver.py)
IrodoriTTS 方式の %date%, %time%, %filename%, %mode% 等のプレースホルダーを展開し、
安全な保存先パス（サブフォルダ自動生成・衝突回避含む）を構築する。
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.paths import BASE_DIR, DEFAULT_OUTPUT_DIR

_INVALID_WIN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_part(name: str) -> str:
    """Windowsファイル名として不正な文字をアンダースコアに置換する。"""
    cleaned = _INVALID_WIN_CHARS.sub("_", name).strip(" .")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned


def _expand_placeholders(text: str, stem: str, mode: str, now: datetime) -> str:
    """文字列内の時刻・ファイル名マクロを展開する。"""
    stamp_date = now.strftime("%Y-%m-%d")
    stamp_time = now.strftime("%H-%M-%S")
    stamp_datetime = f"{stamp_date}_{stamp_time}"

    return (
        text.replace("%datetime%", stamp_datetime)
        .replace("%date%", stamp_date)
        .replace("%time%", stamp_time)
        .replace("%YYYY%", now.strftime("%Y"))
        .replace("%MM%", now.strftime("%m"))
        .replace("%DD%", now.strftime("%d"))
        .replace("%hh%", now.strftime("%H"))
        .replace("%mm%", now.strftime("%M"))
        .replace("%ss%", now.strftime("%S"))
        .replace("%filename%", sanitize_filename_part(stem))
        .replace("%mode%", sanitize_filename_part(mode))
    )


def resolve_output_dir(output_dir_raw: str, original_filename: str = "sample", mode: str = "vocal_extract", now: Optional[datetime] = None) -> Path:
    """保存先ベースフォルダパス（マクロ展開済み絶対パス）を返す。"""
    dt = now or datetime.now()
    stem = Path(original_filename).stem if original_filename else "audio"
    raw = (output_dir_raw or "").strip()
    if not raw:
        return DEFAULT_OUTPUT_DIR

    expanded = _expand_placeholders(raw, stem, mode, dt)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    return candidate


def resolve_output_path(
    output_dir_raw: str,
    pattern_raw: str,
    original_filename: str,
    mode: str,
    suffix_with_ext: str,
    now: Optional[datetime] = None,
    ensure_unique: bool = True,
) -> Path:
    """
    ベースフォルダ＋プリフィックスパターン＋種別サフィックスを結合した最終保存パスを返す。

    Args:
        output_dir_raw: 保存先ベースフォルダ入力値
        pattern_raw: サブフォルダ・ファイル名パターン (例: "%date%\\%time%_%filename%")
        original_filename: 元ファイル名 (例: "sample_video.mp4")
        mode: 処理モード名
        suffix_with_ext: 種別サフィックス付き拡張子 (例: "_vocal.wav", "_replaced.mp4")
        now: 基準時刻（省略時は現在時刻）
        ensure_unique: 既存ファイルとの衝突時に連番を付与するか
    """
    dt = now or datetime.now()
    stem = Path(original_filename).stem if original_filename else "output"
    base_dir = resolve_output_dir(output_dir_raw, original_filename, mode, dt)

    pattern = (pattern_raw or "").strip()
    if not pattern:
        pattern = "%date%\\%time%_%filename%"

    expanded_pattern = _expand_placeholders(pattern, stem, mode, dt)
    raw_parts = [p for p in re.split(r"[\\/]+", expanded_pattern) if p and p not in (".", "..")]

    if not raw_parts:
        raw_parts = [sanitize_filename_part(stem) or "output"]

    subfolders = [sanitize_filename_part(p) for p in raw_parts[:-1] if sanitize_filename_part(p)]
    file_stem = sanitize_filename_part(raw_parts[-1]).strip("_") or "output"

    target_dir = base_dir.joinpath(*subfolders) if subfolders else base_dir
    final_path = target_dir / f"{file_stem}{suffix_with_ext}"

    if ensure_unique:
        final_path = make_unique_path(final_path)
    return final_path


def make_unique_path(path: Path) -> Path:
    """同名ファイルが既に存在する場合に _001, _002 ... を付与して上書きを防ぐ。"""
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
