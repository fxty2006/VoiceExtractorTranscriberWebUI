"""
一時プレビュー管理モジュール (app/temp_manager.py)
temp_preview/ 内のファイル件数・容量を監視し、手動一括削除やフォルダ表示を提供する。
（※意図しないファイル消失を防ぐため、時間経過による自動削除は行わない）
"""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from app.paths import TEMP_PREVIEW_DIR


def get_temp_status(exclude_session_id: Optional[str] = None) -> Dict[str, Any]:
    """temp_preview/ 内の蓄積状況（件数・バイト数・MB・注意書きメッセージ）を返す。"""
    TEMP_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    total_files = 0
    total_bytes = 0
    past_files = 0
    past_bytes = 0

    for entry in TEMP_PREVIEW_DIR.iterdir():
        if entry.is_dir():
            is_current = exclude_session_id is not None and entry.name == exclude_session_id
            for f in entry.rglob("*"):
                if f.is_file():
                    size = f.stat().st_size
                    total_files += 1
                    total_bytes += size
                    if not is_current:
                        past_files += 1
                        past_bytes += size
        elif entry.is_file():
            size = entry.stat().st_size
            total_files += 1
            total_bytes += size
            past_files += 1
            past_bytes += size

    total_mb = round(total_bytes / (1024 * 1024), 1)
    past_mb = round(past_bytes / (1024 * 1024), 1)
    has_past_files = past_files > 0
    has_any_files = total_files > 0

    if has_past_files:
        alert_text = f"⚠️ Tempフォルダに過去のプレビューが貯まっています（過去分: {past_files}件 / {past_mb:.1f} MB、全体: {total_files}件 / {total_mb:.1f} MB）"
    elif has_any_files:
        alert_text = f"ℹ️ 現在の作業プレビューのみ保持中です（{total_files}件 / {total_mb:.1f} MB）"
    else:
        alert_text = "✅ Tempフォルダはクリーンな状態です（0件 / 0.0 MB）"

    return {
        "temp_dir": str(TEMP_PREVIEW_DIR),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_mb": total_mb,
        "past_files": past_files,
        "past_bytes": past_bytes,
        "past_mb": past_mb,
        "has_past_files": has_past_files,
        "has_any_files": has_any_files,
        "alert_text": alert_text,
    }


def clear_temp_preview(exclude_session_id: Optional[str] = None) -> Dict[str, Any]:
    """temp_preview/ 内のファイルを手動で一括削除する。"""
    TEMP_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    deleted_count = 0

    for entry in list(TEMP_PREVIEW_DIR.iterdir()):
        if exclude_session_id and entry.is_dir() and entry.name == exclude_session_id:
            continue
        try:
            if entry.is_dir():
                count = sum(1 for f in entry.rglob("*") if f.is_file())
                shutil.rmtree(entry, ignore_errors=False)
                deleted_count += count
            elif entry.is_file():
                entry.unlink()
                deleted_count += 1
        except Exception as e:
            print(f"[TempManager Warning] 削除に失敗しました ({entry}): {e}")

    status = get_temp_status(exclude_session_id=exclude_session_id)
    status["deleted_count"] = deleted_count
    return status


def open_temp_folder() -> bool:
    """Windows エクスプローラーで temp_preview フォルダを開く。"""
    TEMP_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(TEMP_PREVIEW_DIR))
        return True
    except Exception as e:
        print(f"[TempManager Warning] フォルダを開けませんでした: {e}")
        return False
