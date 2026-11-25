"""
メディア書き出しモジュール (app/media_exporter.py)
1. トラックA/Bのスライダー・ミュート・ソロ反映および 24bit / 48kHz WAV 本保存
2. ffmpeg 映像無劣化（-c:v copy）での音声差し替え MP4 本保存
3. ffmpeg 映像無劣化（-c:v copy -an）での映像のみ MP4 本保存
4. 文字起こしテキスト（.txt）および字幕ファイル（.srt）の本保存
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import soundfile as sf

from app.paths import resolve_ffmpeg
from app.prefix_resolver import resolve_output_path

TARGET_SR = 48000


def compute_effective_gains(
    vol_a_pct: float = 100.0,
    vol_b_pct: float = 0.0,
    mute_a: bool = False,
    mute_b: bool = False,
    solo_a: bool = False,
    solo_b: bool = False,
) -> tuple[float, float]:
    """UI上のスライダー・ミュート・ソロ状態から最終ゲイン倍率（0.0〜1.5）を算出する。"""
    any_solo = bool(solo_a or solo_b)
    active_a = (not mute_a) and ((not any_solo) or solo_a)
    active_b = (not mute_b) and ((not any_solo) or solo_b)

    gain_a = (max(0.0, min(150.0, float(vol_a_pct))) / 100.0) if active_a else 0.0
    gain_b = (max(0.0, min(150.0, float(vol_b_pct))) / 100.0) if active_b else 0.0
    return gain_a, gain_b


def _load_master_tracks(session_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """32bit float のマスターWAV（A・B）を読み込む。"""
    path_a = session_dir / "track_a_master.wav"
    path_b = session_dir / "track_b_master.wav"
    if not path_a.exists() or not path_b.exists():
        raise FileNotFoundError("分離済みマスタートラックが見つかりません。先に音声分離を実行してください。")
    audio_a, sr_a = sf.read(str(path_a), dtype="float32", always_2d=True)
    audio_b, sr_b = sf.read(str(path_b), dtype="float32", always_2d=True)
    if sr_a != TARGET_SR or sr_b != TARGET_SR:
        raise ValueError("マスター音声のサンプルレートが48kHzと一致しません。")
    min_len = min(audio_a.shape[0], audio_b.shape[0])
    return audio_a[:min_len], audio_b[:min_len]


def export_adjusted_wav(
    session_dir: Path,
    output_dir: str,
    filename_pattern: str,
    original_filename: str,
    mode: str,
    wav_target: str = "vocal",
    vol_a_pct: float = 100.0,
    vol_b_pct: float = 0.0,
    mute_a: bool = False,
    mute_b: bool = False,
    solo_a: bool = False,
    solo_b: bool = False,
    now: Optional[datetime] = None,
) -> List[str]:
    """調整済み音声を 24bit / 48kHz 非圧縮WAV（PCM_24）で本保存し、出力パス一覧を返す。"""
    audio_a, audio_b = _load_master_tracks(session_dir)
    gain_a, gain_b = compute_effective_gains(vol_a_pct, vol_b_pct, mute_a, mute_b, solo_a, solo_b)
    ts = now or datetime.now()
    saved_paths: List[str] = []

    def _write_24bit(data: np.ndarray, suffix: str) -> str:
        out_path = resolve_output_path(
            output_dir_raw=output_dir,
            pattern_raw=filename_pattern,
            original_filename=original_filename,
            mode=mode,
            suffix_with_ext=suffix,
            now=ts,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), np.clip(data, -1.0, 1.0), TARGET_SR, subtype="PCM_24")
        return str(out_path)

    if wav_target == "vocal":
        saved_paths.append(_write_24bit(audio_a * gain_a, "_vocal.wav"))
    elif wav_target == "bgm":
        # bgm単体保存時、仮にスライダーが0%でもそのまま聴きたい場合は100%フォールバックせず、
        # Bトラック単独出力意図を考慮してgain_bが0なら1.0で出力する安全ガード
        effective_b = gain_b if gain_b > 0.0 else 1.0
        saved_paths.append(_write_24bit(audio_b * effective_b, "_bgm.wav"))
    elif wav_target == "both":
        saved_paths.append(_write_24bit(audio_a * gain_a, "_vocal.wav"))
        effective_b = gain_b if gain_b > 0.0 else 1.0
        saved_paths.append(_write_24bit(audio_b * effective_b, "_bgm.wav"))
    else:
        # mixed
        mixed = audio_a * gain_a + audio_b * gain_b
        saved_paths.append(_write_24bit(mixed, "_mixed.wav"))

    return saved_paths


def export_replaced_mp4(
    session_dir: Path,
    source_video_path: Path,
    output_dir: str,
    filename_pattern: str,
    original_filename: str,
    mode: str,
    wav_target: str = "vocal",
    vol_a_pct: float = 100.0,
    vol_b_pct: float = 0.0,
    mute_a: bool = False,
    mute_b: bool = False,
    solo_a: bool = False,
    solo_b: bool = False,
    now: Optional[datetime] = None,
) -> str:
    """元動画の映像ストリームを無劣化コピー（-c:v copy）し、調整後の音声へ差し替えたMP4を保存する。"""
    if not source_video_path.exists():
        raise FileNotFoundError("元の動画ファイルが見つかりません。")

    audio_a, audio_b = _load_master_tracks(session_dir)
    gain_a, gain_b = compute_effective_gains(vol_a_pct, vol_b_pct, mute_a, mute_b, solo_a, solo_b)

    if wav_target == "vocal":
        audio_data = audio_a * gain_a
    elif wav_target == "bgm":
        audio_data = audio_b * (gain_b if gain_b > 0.0 else 1.0)
    else:
        audio_data = audio_a * gain_a + audio_b * gain_b

    tmp_wav = session_dir / "_tmp_export_audio.wav"
    sf.write(str(tmp_wav), np.clip(audio_data, -1.0, 1.0), TARGET_SR, subtype="PCM_24")

    ts = now or datetime.now()
    out_path = resolve_output_path(
        output_dir_raw=output_dir,
        pattern_raw=filename_pattern,
        original_filename=original_filename,
        mode=mode,
        suffix_with_ext="_replaced.mp4",
        now=ts,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = resolve_ffmpeg()

    try:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", str(source_video_path),
            "-i", str(tmp_wav),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "320k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            # 一部の非MP4コンテナ(AVI等)で映像コピーが拒否された場合のみ互換エンコードで再試行
            cmd_fallback = [
                ffmpeg_bin,
                "-y",
                "-i", str(source_video_path),
                "-i", str(tmp_wav),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "16",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "320k",
                "-movflags", "+faststart",
                str(out_path),
            ]
            proc2 = subprocess.run(cmd_fallback, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc2.returncode != 0:
                raise RuntimeError(f"音声差し替えMP4の生成に失敗しました: {proc2.stderr[-500:]}")
    finally:
        if tmp_wav.exists():
            tmp_wav.unlink()

    return str(out_path)


def export_video_only_mp4(
    source_video_path: Path,
    output_dir: str,
    filename_pattern: str,
    original_filename: str,
    mode: str,
    now: Optional[datetime] = None,
) -> str:
    """元動画から音声ストリームを除去し、映像のみを無劣化コピー（-c:v copy -an）で保存する。"""
    if not source_video_path.exists():
        raise FileNotFoundError("元の動画ファイルが見つかりません。")

    ts = now or datetime.now()
    out_path = resolve_output_path(
        output_dir_raw=output_dir,
        pattern_raw=filename_pattern,
        original_filename=original_filename,
        mode=mode,
        suffix_with_ext="_video_only.mp4",
        now=ts,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = resolve_ffmpeg()

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(source_video_path),
        "-c:v", "copy",
        "-an",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        cmd_fallback = [
            ffmpeg_bin,
            "-y",
            "-i", str(source_video_path),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "16",
            "-pix_fmt", "yuv420p",
            "-an",
            "-movflags", "+faststart",
            str(out_path),
        ]
        proc2 = subprocess.run(cmd_fallback, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc2.returncode != 0:
            raise RuntimeError(f"映像のみMP4の生成に失敗しました: {proc2.stderr[-500:]}")

    return str(out_path)


def export_transcript_files(
    output_dir: str,
    filename_pattern: str,
    original_filename: str,
    mode: str,
    text_content: str,
    srt_content: str = "",
    now: Optional[datetime] = None,
) -> List[str]:
    """文字起こしテキスト（.txt）および字幕（.srt）を本保存し、保存パス一覧を返す。"""
    if not text_content.strip():
        raise ValueError("保存する文字起こしテキストが空です。")

    ts = now or datetime.now()
    saved_paths: List[str] = []

    txt_path = resolve_output_path(
        output_dir_raw=output_dir,
        pattern_raw=filename_pattern,
        original_filename=original_filename,
        mode=mode,
        suffix_with_ext="_transcript.txt",
        now=ts,
    )
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(text_content, encoding="utf-8")
    saved_paths.append(str(txt_path))

    if srt_content.strip():
        srt_path = resolve_output_path(
            output_dir_raw=output_dir,
            pattern_raw=filename_pattern,
            original_filename=original_filename,
            mode=mode,
            suffix_with_ext="_subtitles.srt",
            now=ts,
        )
        srt_path.parent.mkdir(parents=True, exist_ok=True)
        srt_path.write_text(srt_content, encoding="utf-8")
        saved_paths.append(str(srt_path))

    return saved_paths


def export_all_media(
    session_dir: Path,
    output_dir: str,
    filename_pattern: str,
    original_filename: str,
    mode: str,
    has_video: bool = False,
    source_video_path: Optional[Path] = None,
    vol_a_pct: float = 100.0,
    vol_b_pct: float = 100.0,
    mute_a: bool = False,
    mute_b: bool = False,
    solo_a: bool = False,
    solo_b: bool = False,
    text_content: Optional[str] = None,
    srt_content: Optional[str] = None,
) -> List[str]:
    """
    全成果物を同一の基準日時（同一タイムスタンプ）でアトミックに書き出し、保存パス一覧を返す。
    - トラックA WAV
    - トラックB WAV
    - (動画時) 音声差し替え MP4
    - (動画時) 映像のみ MP4
    - (文字起こし時) TXT
    - (文字起こし時) SRT
    """
    now = datetime.now()
    saved_paths: List[str] = []

    # 1. トラックA & B を個別WAV出力
    wav_paths = export_adjusted_wav(
        session_dir=session_dir,
        output_dir=output_dir,
        filename_pattern=filename_pattern,
        original_filename=original_filename,
        mode=mode,
        wav_target="both",
        vol_a_pct=vol_a_pct,
        vol_b_pct=vol_b_pct,
        mute_a=mute_a,
        mute_b=mute_b,
        solo_a=solo_a,
        solo_b=solo_b,
        now=now,
    )
    saved_paths.extend(wav_paths)

    # 2. 動画の場合、差し替えMP4と映像のみMP4を出力
    if has_video and source_video_path and source_video_path.exists():
        rep_mp4 = export_replaced_mp4(
            session_dir=session_dir,
            source_video_path=source_video_path,
            output_dir=output_dir,
            filename_pattern=filename_pattern,
            original_filename=original_filename,
            mode=mode,
            wav_target="vocal",
            vol_a_pct=vol_a_pct,
            vol_b_pct=vol_b_pct,
            mute_a=mute_a,
            mute_b=mute_b,
            solo_a=solo_a,
            solo_b=solo_b,
            now=now,
        )
        saved_paths.append(rep_mp4)

        vo_mp4 = export_video_only_mp4(
            source_video_path=source_video_path,
            output_dir=output_dir,
            filename_pattern=filename_pattern,
            original_filename=original_filename,
            mode=mode,
            now=now,
        )
        saved_paths.append(vo_mp4)

    # 3. 文字起こしテキスト・字幕がある場合
    if text_content and text_content.strip():
        txt_paths = export_transcript_files(
            output_dir=output_dir,
            filename_pattern=filename_pattern,
            original_filename=original_filename,
            mode=mode,
            text_content=text_content,
            srt_content=srt_content or "",
            now=now,
        )
        saved_paths.extend(txt_paths)

    return saved_paths
