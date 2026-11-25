"""
オンデマンド文字起こしモジュール (app/transcriber.py)
トラックA（抽出された声）からテキストおよびタイムスタンプ（SRT）を生成する。
既存のDドライブ内ローカルモデル（large-v3-turbo-local）を最優先で使用し、
オフライン完結かつ高速にGPU推論を行う。
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import torch

from app.paths import EXTERNAL_LOCAL_OPENAI_WHISPER_PT, EXTERNAL_LOCAL_WHISPER_DIR, MODELS_DIR

_MODEL_INSTANCE: Optional[Dict[str, Any]] = None


def format_display_time(seconds: float) -> str:
    """表示用タイムスタンプ [MM:SS.xx] 文字列へ変換する。"""
    sec = max(0.0, float(seconds))
    mins = int(sec // 60)
    rem = sec - mins * 60
    return f"{mins:02d}:{rem:05.2f}"


def format_srt_time(seconds: float) -> str:
    """SRT字幕標準形式 HH:MM:SS,mmm へ変換する。"""
    ms_total = max(0, int(round(float(seconds) * 1000)))
    hours = ms_total // 3_600_000
    ms_total %= 3_600_000
    minutes = ms_total // 60_000
    ms_total %= 60_000
    secs = ms_total // 1000
    millis = ms_total % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_text(segments: List[Dict[str, Any]], use_timestamps: bool = True) -> str:
    """セグメント配列から表示用テキストを生成する。"""
    lines: List[str] = []
    for seg in segments:
        txt = str(seg.get("text", "")).strip()
        if not txt:
            continue
        if use_timestamps:
            st = format_display_time(seg.get("start", 0.0))
            ed = format_display_time(seg.get("end", 0.0))
            lines.append(f"[{st} --> {ed}] {txt}")
        else:
            lines.append(txt)
    return "\n".join(lines)


def segments_to_srt(segments: List[Dict[str, Any]]) -> str:
    """セグメント配列から DaVinci Resolve 互換の SRT 字幕テキストを生成する。"""
    blocks: List[str] = []
    idx = 1
    for seg in segments:
        txt = str(seg.get("text", "")).strip()
        if not txt:
            continue
        st = format_srt_time(seg.get("start", 0.0))
        ed = format_srt_time(seg.get("end", 0.0))
        blocks.append(f"{idx}\n{st} --> {ed}\n{txt}")
        idx += 1
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _load_transcriber_engine(force_device: Optional[str] = None) -> Dict[str, Any]:
    """利用可能な文字起こしエンジン（faster-whisper優先、次点でopenai-whisper）をロードする。"""
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is not None and force_device is None:
        return _MODEL_INSTANCE

    device = force_device or ("cuda" if torch.cuda.is_available() else "cpu")

    # 1. faster-whisper（ローカルモデル優先）
    try:
        from faster_whisper import WhisperModel  # type: ignore

        compute_type = "float16" if device == "cuda" else "int8"
        if EXTERNAL_LOCAL_WHISPER_DIR.exists():
            model = WhisperModel(
                str(EXTERNAL_LOCAL_WHISPER_DIR),
                device=device,
                compute_type=compute_type,
                local_files_only=True,
            )
        else:
            fw_dir = MODELS_DIR / "faster-whisper"
            fw_dir.mkdir(parents=True, exist_ok=True)
            model = WhisperModel(
                "large-v3-turbo",
                device=device,
                compute_type=compute_type,
                download_root=str(fw_dir),
            )
        _MODEL_INSTANCE = {"engine": "faster-whisper", "model": model, "device": device}
        return _MODEL_INSTANCE
    except ImportError:
        pass
    except Exception as e:
        print(f"[Transcriber Warning] faster-whisperロード失敗、フォールバックを試行します: {e}")

    # 2. openai-whisper フォールバック
    try:
        import whisper  # type: ignore

        w_dir = MODELS_DIR / "whisper"
        w_dir.mkdir(parents=True, exist_ok=True)
        model_target = str(EXTERNAL_LOCAL_OPENAI_WHISPER_PT) if EXTERNAL_LOCAL_OPENAI_WHISPER_PT.exists() else "turbo"
        model = whisper.load_model(model_target, device=device, download_root=str(w_dir))
        _MODEL_INSTANCE = {"engine": "openai-whisper", "model": model, "device": device}
        return _MODEL_INSTANCE
    except Exception as e:
        raise RuntimeError(
            f"文字起こしエンジン (faster-whisper / openai-whisper) のロードに失敗しました: {e}"
        ) from e


PROMPT_PRESETS: Dict[str, Dict[str, Any]] = {
    "standard": {
        "name": "通常（標準・感嘆音抑制）",
        "prompt_ja": None,
        "prompt_en": None,
        "vad_threshold": 0.50,
        "no_speech_threshold": 0.60,
        "log_prob_threshold": -1.0,
        "compression_ratio_threshold": 2.4,
        "condition_on_previous_text": True,
        "use_vad": True,
        "speech_pad_ms": 400,
        "min_speech_duration_ms": 250,
        "min_silence_duration_ms": 2000,
    },
    "laughter_emotion": {
        "name": "笑い声・感情・相槌 (あはは等)",
        "prompt_ja": "あははは、ふふふ、ははは、えー、あのー、やだもう。",
        "prompt_en": "Haha, hahaha, oh, wow, yeah.",
        "vad_threshold": 0.15,
        "no_speech_threshold": 0.85,
        "log_prob_threshold": -1.2,
        "compression_ratio_threshold": 2.4,
        "condition_on_previous_text": True,
        "use_vad": True,
        "speech_pad_ms": 800,
        "min_speech_duration_ms": 100,
        "min_silence_duration_ms": 1000,
    },
    "sigh_gasp_shout": {
        "name": "含み音・吐息・叫び・息遣い特化 (ふぅ/ぐぬぬ/あっ/きゃー等)",
        "prompt_ja": "ふぅ…、はぁ…、ぐぬぬ…、あっ…、んっ…、きゃー！、うわぁ！、息遣い、ため息、叫び。",
        "prompt_en": "Sigh..., gasp..., ah..., scream!, breathing.",
        "vad_threshold": 0.08,
        "no_speech_threshold": 0.90,
        "log_prob_threshold": -1.5,
        "compression_ratio_threshold": 2.3,
        "condition_on_previous_text": False,
        "use_vad": True,
        "speech_pad_ms": 1000,
        "min_speech_duration_ms": 40,
        "min_silence_duration_ms": 1200,
    },
    "action_shouts": {
        "name": "掛け声・気合・アクション特化 (えい！/やぁ！/とぅ！/うんしょ！等)",
        "prompt_ja": "えい！、やぁ！、とぅ！、うんしょ！、はっ！、よっ！、うおっ！、あっ！、せーの！",
        "prompt_en": "Hey!, Hah!, Yah!, Hmph!, Ngh!, Ah!",
        "vad_threshold": 0.05,
        "no_speech_threshold": 0.95,
        "log_prob_threshold": -1.8,
        "compression_ratio_threshold": 2.2,
        "condition_on_previous_text": False,
        "use_vad": False,
        "speech_pad_ms": 1000,
        "min_speech_duration_ms": 30,
        "min_silence_duration_ms": 800,
    },
    "custom": {
        "name": "カスタム自由入力",
        "prompt_ja": "",
        "prompt_en": "",
        "vad_threshold": 0.15,
        "no_speech_threshold": 0.85,
        "log_prob_threshold": -1.2,
        "compression_ratio_threshold": 2.4,
        "condition_on_previous_text": True,
        "use_vad": True,
        "speech_pad_ms": 800,
        "min_speech_duration_ms": 100,
        "min_silence_duration_ms": 1000,
    },
}


def transcribe_audio(
    wav_path: Path,
    language: str = "ja",
    use_timestamps: bool = True,
    disable_vad: bool = False,
    include_laughs: bool = False,
    prompt_preset: str = "standard",
    custom_prompt: str = "",
    progress_cb: Optional[Callable[[str, int], None]] = None,
) -> Dict[str, Any]:
    """
    指定WAVファイル（トラックA）の文字起こしを実行し、
    表示テキスト・SRTテキスト・セグメント一覧を返す。
    """
    if progress_cb:
        progress_cb("faster-whisper モデル準備中...", 5)

    if not wav_path.exists():
        raise FileNotFoundError(f"文字起こし対象の音声ファイルが見つかりません: {wav_path}")

    engine_info = _load_transcriber_engine()
    engine_name = engine_info["engine"]
    model = engine_info["model"]
    lang_arg = None if language in ("", "auto", None) else language

    # プリセット解決
    resolved_preset_key = prompt_preset if prompt_preset in PROMPT_PRESETS else (
        "laughter_emotion" if include_laughs else "standard"
    )
    preset_cfg = PROMPT_PRESETS.get(resolved_preset_key, PROMPT_PRESETS["standard"])
    effective_vad = False if disable_vad else bool(preset_cfg.get("use_vad", True))

    if resolved_preset_key == "custom":
        active_prompt = custom_prompt.strip() or None
    elif resolved_preset_key == "standard":
        active_prompt = None
    else:
        active_prompt = preset_cfg["prompt_ja"] if lang_arg in (None, "ja") else preset_cfg["prompt_en"]

    segments_list: List[Dict[str, Any]] = []
    detected_lang = language

    if engine_name == "faster-whisper":
        def _collect_segments(target_model: Any, vad_enabled: bool) -> tuple[List[Dict[str, Any]], Any]:
            kw: Dict[str, Any] = {
                "language": lang_arg,
                "vad_filter": vad_enabled,
                "beam_size": 5,
                "compression_ratio_threshold": float(preset_cfg.get("compression_ratio_threshold", 2.4)),
                "condition_on_previous_text": (
                    False if not vad_enabled else bool(preset_cfg.get("condition_on_previous_text", True))
                ),
            }
            if active_prompt:
                kw["initial_prompt"] = active_prompt

            if not vad_enabled:
                # VAD無効時は短い掛け声等を捨てないよう無音判定も緩和し、無音幻覚抑制を併用する
                kw["no_speech_threshold"] = max(0.95, float(preset_cfg.get("no_speech_threshold", 0.95)))
                kw["log_prob_threshold"] = min(-1.8, float(preset_cfg.get("log_prob_threshold", -1.8)))
                kw["word_timestamps"] = True
                kw["hallucination_silence_threshold"] = 2.0
            elif resolved_preset_key != "standard":
                kw["no_speech_threshold"] = preset_cfg["no_speech_threshold"]
                kw["log_prob_threshold"] = preset_cfg["log_prob_threshold"]

            if vad_enabled:
                if resolved_preset_key != "standard":
                    kw["vad_parameters"] = {
                        "threshold": preset_cfg["vad_threshold"],
                        "min_speech_duration_ms": preset_cfg["min_speech_duration_ms"],
                        "min_silence_duration_ms": preset_cfg["min_silence_duration_ms"],
                        "speech_pad_ms": preset_cfg["speech_pad_ms"],
                    }
                else:
                    kw["vad_parameters"] = {
                        "threshold": preset_cfg["vad_threshold"],
                    }

            raw_iter, meta_info = target_model.transcribe(str(wav_path), **kw)
            total_duration = max(0.1, float(getattr(meta_info, "duration", 0.0) or 0.0))
            if progress_cb:
                mode_label = "全区間認識(VAD無効)" if not vad_enabled else "音声認識中"
                progress_cb(f"faster-whisper {mode_label}...", 10)

            collected: List[Dict[str, Any]] = []
            for s in raw_iter:
                txt = str(s.text).replace("\ufffd", "").strip()
                if txt:
                    collected.append({
                        "start": round(float(s.start), 3),
                        "end": round(float(s.end), 3),
                        "text": txt,
                    })
                if progress_cb and total_duration > 0:
                    pct = min(90, 10 + int(80 * (float(s.end) / total_duration)))
                    progress_cb(f"文字起こし推論中 ({float(s.end):.1f}秒 / 全{total_duration:.1f}秒)", pct)
            return collected, meta_info

        def _run_with_vad_fallback(target_model: Any) -> tuple[List[Dict[str, Any]], Any]:
            segs, meta_i = _collect_segments(target_model, effective_vad)
            if effective_vad and not segs:
                segs, meta_retry = _collect_segments(target_model, False)
                meta_i = meta_i or meta_retry
            return segs, meta_i

        try:
            segments_list, info = _run_with_vad_fallback(model)
        except RuntimeError as rt_err:
            if engine_info.get("device") == "cpu":
                raise
            print(f"[Transcriber Warning] faster-whisper GPU実行時エラーのためCPU(int8)へ自動切替します: {rt_err}")
            engine_info = _load_transcriber_engine(force_device="cpu")
            model = engine_info["model"]
            segments_list, info = _run_with_vad_fallback(model)
        detected_lang = getattr(info, "language", language)
    else:
        use_fp16 = engine_info.get("device") == "cuda"
        ow_kw: Dict[str, Any] = {
            "language": lang_arg,
            "fp16": use_fp16,
        }
        if active_prompt:
            ow_kw["initial_prompt"] = active_prompt
        result = model.transcribe(str(wav_path), **ow_kw)
        detected_lang = str(result.get("language", language))
        for s in result.get("segments", []):
            txt = str(s.get("text", "")).replace("\ufffd", "").strip()
            if txt:
                segments_list.append({
                    "start": round(float(s.get("start", 0.0)), 3),
                    "end": round(float(s.get("end", 0.0)), 3),
                    "text": txt,
                })

    if progress_cb:
        progress_cb("字幕・テキスト整形中...", 95)

    res = {
        "engine": engine_name,
        "language": detected_lang,
        "segments": segments_list,
        "text": segments_to_text(segments_list, use_timestamps=use_timestamps),
        "plain_text": segments_to_text(segments_list, use_timestamps=False),
        "timestamp_text": segments_to_text(segments_list, use_timestamps=True),
        "srt_text": segments_to_srt(segments_list),
    }

    if progress_cb:
        progress_cb("完了", 100)

    return res