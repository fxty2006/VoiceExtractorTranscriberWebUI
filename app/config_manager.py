"""
設定管理モジュール (app/config_manager.py)
IrodoriTTS 方式の defaults / saved 2層JSON構造で設定の読み込み・保存・初期化を行う。
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict

from app.paths import BASE_DIR, CONFIG_PATH, DEFAULT_OUTPUT_DIR

SYSTEM_DEFAULT_CONFIG: Dict[str, Any] = {
    "output_dir": "outputs",
    "filename_pattern": "%date%\\%time%_%filename%",
    "process_mode": "vocal_extract",
    "model_name": "uvr_mdx_net_inst_hq_5",
    "strength": 85,
    "wav_target": "vocal",
    "slider_vol_a": 100,
    "slider_vol_b": 100,
    "mute_a": False,
    "mute_b": False,
    "language": "ja",
    "use_timestamps": True,
    "disable_vad": False,
    "include_laughs": False,
    "prompt_preset": "standard",
    "custom_prompt": "",
}


def load_defaults() -> Dict[str, Any]:
    """出荷時推奨初期値のディープコピーを返す。"""
    return copy.deepcopy(SYSTEM_DEFAULT_CONFIG)


def reset_to_defaults() -> Dict[str, Any]:
    """config.json の saved セクションを出荷時初期値で上書きして初期化する。"""
    defaults = load_defaults()
    payload = {
        "defaults": defaults,
        "saved": copy.deepcopy(defaults),
    }
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Config Error] 設定初期化保存に失敗しました ({CONFIG_PATH}): {e}")
    return defaults


def load_saved_config() -> Dict[str, Any]:
    """config.json の 'saved' セクションから設定を読み込む。欠落キーは初期値で補完する。"""
    merged = load_defaults()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                saved_data = data.get("saved", data) if "saved" in data else data
                if isinstance(saved_data, dict):
                    for key, value in saved_data.items():
                        if key in merged:
                            merged[key] = value
        except Exception as e:
            print(f"[Config Warning] 設定ファイル読み込みに失敗しました ({CONFIG_PATH}): {e}")
    return merged


def save_config(new_values: Dict[str, Any]) -> Dict[str, Any]:
    """指定された設定値を既存保存値とマージして config.json に保存する。"""
    merged = load_saved_config()
    for key, value in new_values.items():
        if key in SYSTEM_DEFAULT_CONFIG:
            merged[key] = value

    payload = {
        "defaults": load_defaults(),
        "saved": merged,
    }
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Config Error] 設定ファイル保存に失敗しました ({CONFIG_PATH}): {e}")
    return merged


def select_output_dir(current_dir: str = "") -> str:
    """OS標準のフォルダ選択ダイアログを開き、選択されたパス文字列を返す。"""
    try:
        import tkinter as tk
        from tkinter import filedialog

        init_dir = DEFAULT_OUTPUT_DIR
        if current_dir:
            candidate = Path(current_dir)
            init_dir = candidate if candidate.is_absolute() else (BASE_DIR / candidate)
        init_dir.mkdir(parents=True, exist_ok=True)

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title="保存先フォルダを選択",
            initialdir=str(init_dir),
        )
        root.destroy()
        return selected if selected else current_dir
    except Exception as e:
        print(f"[GUI Warning] フォルダ選択ダイアログを開けませんでした: {e}")
        return current_dir