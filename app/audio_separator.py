"""
音声分離・ノイズ除去・メディア解析モジュール (app/audio_separator.py)
ffmpeg による音声/無音映像展開、Hybrid Demucs によるGPU音源分離、
STFTスペクトルゲーティングによる定常ノイズ除去、および波形ピーク算出を担当する。
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
import torch
import torchaudio
from scipy import signal

from app.paths import is_video_extension, resolve_ffmpeg, resolve_ffprobe

TARGET_SR = 48000
DEMUCS_SR = 44100

_DEMUCS_MODEL_CACHE: Dict[str, Any] = {}


def _get_hdemucs_model(device: torch.device) -> Any:
    """torchaudio標準の Hybrid Demucs モデルをシングルトンロードする（重みは TORCH_HOME 配下へ保存）。"""
    key = str(device)
    if key not in _DEMUCS_MODEL_CACHE:
        bundle = torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS
        model = bundle.get_model().to(device)
        model.eval()
        _DEMUCS_MODEL_CACHE[key] = model
    return _DEMUCS_MODEL_CACHE[key]


def probe_media_info(file_path: Path) -> Dict[str, Any]:
    """ffprobe または soundfile を用いて動画・音声のメタ情報を取得する。"""
    info: Dict[str, Any] = {
        "duration": 0.0,
        "has_video": is_video_extension(file_path.name),
        "has_audio": True,
        "video_codec": "",
        "audio_sr": 0,
        "channels": 0,
        "width": 0,
        "height": 0,
    }

    ffprobe_bin = resolve_ffprobe()
    if ffprobe_bin:
        cmd = [
            ffprobe_bin,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                fmt = data.get("format", {})
                if "duration" in fmt:
                    info["duration"] = float(fmt["duration"])
                streams = data.get("streams", [])
                v_streams = [s for s in streams if s.get("codec_type") == "video"]
                a_streams = [s for s in streams if s.get("codec_type") == "audio"]
                info["has_video"] = len(v_streams) > 0
                info["has_audio"] = len(a_streams) > 0
                if v_streams:
                    vs = v_streams[0]
                    info["video_codec"] = str(vs.get("codec_name", ""))
                    info["width"] = int(vs.get("width", 0) or 0)
                    info["height"] = int(vs.get("height", 0) or 0)
                if a_streams:
                    as_ = a_streams[0]
                    info["audio_sr"] = int(as_.get("sample_rate", 0) or 0)
                    info["channels"] = int(as_.get("channels", 0) or 0)
                return info
        except Exception as e:
            print(f"[MediaProbe Warning] ffprobe解析に失敗しました: {e}")

    # フォールバック（音声ファイル直接読み取り）
    try:
        sf_info = sf.info(str(file_path))
        info["duration"] = float(sf_info.duration)
        info["audio_sr"] = int(sf_info.samplerate)
        info["channels"] = int(sf_info.channels)
    except Exception:
        pass
    return info


def prepare_session_media(input_path: Path, session_dir: Path) -> Dict[str, Any]:
    """
    アップロードされた元ファイルから以下を準備する:
    1. 処理用 48kHz ステレオWAV (original_48k.wav)
    2. 動画の場合は同期再生用の音声ミュート済み映像 (video_preview.mp4)
    """
    ffmpeg_bin = resolve_ffmpeg()
    meta = probe_media_info(input_path)
    if not meta["has_audio"]:
        raise ValueError("入力ファイルに音声ストリームが含まれていません。")

    orig_wav = session_dir / "original_48k.wav"
    cmd_audio = [
        ffmpeg_bin,
        "-y",
        "-i", str(input_path),
        "-vn",
        "-ac", "2",
        "-ar", str(TARGET_SR),
        "-c:a", "pcm_s16le",
        str(orig_wav),
    ]
    proc_audio = subprocess.run(cmd_audio, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc_audio.returncode != 0 or not orig_wav.exists():
        raise RuntimeError(f"音声抽出(ffmpeg)に失敗しました: {proc_audio.stderr[-500:]}")

    # 抽出したWAVから正確な長さを確定
    sf_info = sf.info(str(orig_wav))
    meta["duration"] = float(sf_info.duration)

    video_preview_file: Optional[str] = None
    if meta["has_video"]:
        preview_mp4 = session_dir / "video_preview.mp4"
        cmd_copy = [
            ffmpeg_bin,
            "-y",
            "-i", str(input_path),
            "-an",
            "-c:v", "copy",
            "-movflags", "+faststart",
            str(preview_mp4),
        ]
        proc_vid = subprocess.run(cmd_copy, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc_vid.returncode != 0 or not preview_mp4.exists():
            # コンテナ非互換時はブラウザ互換H.264でプレビュー生成
            cmd_transcode = [
                ffmpeg_bin,
                "-y",
                "-i", str(input_path),
                "-an",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(preview_mp4),
            ]
            proc_vid2 = subprocess.run(cmd_transcode, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc_vid2.returncode == 0 and preview_mp4.exists():
                video_preview_file = preview_mp4.name
        else:
            video_preview_file = preview_mp4.name

    meta["video_preview_file"] = video_preview_file
    meta["original_audio_file"] = orig_wav.name
    return meta


def _separate_with_hdemucs(
    audio_48k: np.ndarray,
    device: torch.device,
    progress_cb: Optional[Callable[[str, int], None]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Hybrid Demucs をスライディングウィンドウ（オーバーラップ・クロスフェード付き）で実行し、
    vocals と bgm (drums + bass + other) を 48kHz ステレオ numpy配列で返す。
    """
    orig_len = audio_48k.shape[0]
    # [samples, 2] -> [2, samples]
    waveform_48k = torch.from_numpy(audio_48k.T).float()
    waveform_44k = torchaudio.functional.resample(waveform_48k, TARGET_SR, DEMUCS_SR)
    total_44k = waveform_44k.shape[1]

    model = _get_hdemucs_model(device)

    chunk_len = DEMUCS_SR * 10
    overlap = DEMUCS_SR * 1
    step = chunk_len - overlap

    vocals_accum = torch.zeros((2, total_44k), dtype=torch.float32)
    bgm_accum = torch.zeros((2, total_44k), dtype=torch.float32)
    weight_accum = torch.zeros((1, total_44k), dtype=torch.float32)

    if total_44k <= chunk_len:
        starts = [0]
    else:
        starts = list(range(0, total_44k, step))

    total_chunks = len(starts)
    with torch.no_grad():
        for idx, start in enumerate(starts):
            if progress_cb:
                pct = 5 + int(75 * idx / max(1, total_chunks))
                progress_cb(f"Demucs 音源分離中 ({idx + 1} / {total_chunks} チャンク)", pct)

            end = min(start + chunk_len, total_44k)
            seg = waveform_44k[:, start:end]
            actual_len = seg.shape[1]

            if actual_len < chunk_len:
                pad = torch.zeros((2, chunk_len - actual_len), dtype=torch.float32)
                seg_in = torch.cat([seg, pad], dim=1)
            else:
                seg_in = seg

            # モデル正規化 (Demucs標準のチャネル平均/標準偏差正規化)
            ref = seg_in.mean(0)
            ref_mean = ref.mean()
            ref_std = ref.std().clamp(min=1e-5)
            norm_in = ((seg_in - ref_mean) / ref_std).unsqueeze(0).to(device)

            out = model(norm_in)  # [1, 4, 2, chunk_len] -> drums, bass, other, vocals
            out = out.squeeze(0).cpu() * ref_std + ref_mean
            out = out[:, :, :actual_len]

            vocals_seg = out[3]
            bgm_seg = out[0] + out[1] + out[2]

            # オーバーラップ境界の三角窓クロスフェード重み
            win = torch.ones((1, actual_len), dtype=torch.float32)
            if start > 0:
                fade_in_len = min(overlap, actual_len)
                win[:, :fade_in_len] *= torch.linspace(0.0, 1.0, fade_in_len)
            if end < total_44k:
                fade_out_len = min(overlap, actual_len)
                win[:, -fade_out_len:] *= torch.linspace(1.0, 0.0, fade_out_len)

            vocals_accum[:, start:end] += vocals_seg * win
            bgm_accum[:, start:end] += bgm_seg * win
            weight_accum[:, start:end] += win

    weight_safe = weight_accum.clamp(min=1e-6)
    vocals_44k = vocals_accum / weight_safe
    bgm_44k = bgm_accum / weight_safe

    vocals_48k = torchaudio.functional.resample(vocals_44k, DEMUCS_SR, TARGET_SR).T.numpy()
    bgm_48k = torchaudio.functional.resample(bgm_44k, DEMUCS_SR, TARGET_SR).T.numpy()

    return _match_length(vocals_48k, orig_len), _match_length(bgm_48k, orig_len)


def _match_length(arr: np.ndarray, target_len: int) -> np.ndarray:
    """音声配列の長さを target_len に正確に揃える。"""
    cur = arr.shape[0]
    if cur == target_len:
        return arr.astype(np.float32, copy=False)
    if cur > target_len:
        return arr[:target_len].astype(np.float32, copy=False)
    pad = np.zeros((target_len - cur, arr.shape[1]), dtype=np.float32)
    return np.vstack([arr.astype(np.float32, copy=False), pad])


def apply_spectral_noise_reduction(audio_48k: np.ndarray, strength: int = 85) -> Tuple[np.ndarray, np.ndarray]:
    """
    STFT スペクトルゲーティングを用いて定常ノイズ（エアコン・ファン・ホワイトノイズ等）を抑制する。
    戻り値: (浄化後音声, 除去されたノイズ成分)
    """
    strength_ratio = max(0.0, min(1.0, float(strength) / 100.0))
    if strength_ratio <= 0.0:
        return audio_48k.copy(), np.zeros_like(audio_48k)

    orig_len = audio_48k.shape[0]
    cleaned_channels = []
    nperseg = 2048
    noverlap = 1536

    # 強度に応じたノイズ減算係数とフロア下限
    alpha = 0.6 + 2.2 * strength_ratio
    floor_min = max(0.02, 0.25 - 0.22 * strength_ratio)

    for ch in range(audio_48k.shape[1]):
        x = audio_48k[:, ch].astype(np.float32)
        _, _, Zxx = signal.stft(x, fs=TARGET_SR, window="hann", nperseg=nperseg, noverlap=noverlap)
        mag = np.abs(Zxx)

        # フレームエネルギー下位20%パーセンタイルをノイズ床と推定
        noise_floor = np.percentile(mag, 20, axis=1, keepdims=True)
        # 周波数方向の軽い平滑化
        noise_floor = signal.convolve2d(noise_floor, np.ones((3, 1)) / 3.0, mode="same", boundary="symm")

        # Wiener風ソフトマスク
        snr_mask = np.clip((mag - alpha * noise_floor) / (mag + 1e-8), floor_min, 1.0)
        # 時間・周波数方向のスムージングでミュージカルノイズ抑制
        kernel = np.ones((3, 3), dtype=np.float32) / 9.0
        smooth_mask = signal.convolve2d(snr_mask, kernel, mode="same", boundary="symm")

        Zxx_clean = Zxx * smooth_mask
        _, x_clean = signal.istft(Zxx_clean, fs=TARGET_SR, window="hann", nperseg=nperseg, noverlap=noverlap)
        cleaned_channels.append(x_clean[:orig_len])

    cleaned = np.stack(cleaned_channels, axis=1).astype(np.float32)
    cleaned = _match_length(cleaned, orig_len)
    removed_noise = (audio_48k.astype(np.float32) - cleaned).astype(np.float32)
    return cleaned, removed_noise


def compute_waveform_peaks(audio_48k: np.ndarray, num_bins: int = 140) -> List[float]:
    """Canvas波形描画用に正規化された絶対値ピーク配列（0.05〜1.0）を算出する。"""
    if audio_48k.size == 0:
        return [0.05] * num_bins
    mono = np.mean(np.abs(audio_48k), axis=1) if audio_48k.ndim > 1 else np.abs(audio_48k)
    total = len(mono)
    if total < num_bins:
        vals = np.interp(np.linspace(0, total - 1, num_bins), np.arange(total), mono)
    else:
        step = total / num_bins
        vals = np.array([
            float(np.max(mono[int(i * step) : max(int(i * step) + 1, int((i + 1) * step))]))
            for i in range(num_bins)
        ])
    peak_max = float(np.max(vals)) if len(vals) > 0 else 0.0
    if peak_max < 1e-6:
        return [0.05] * num_bins
    normalized = np.clip(vals / peak_max, 0.05, 1.0)
    return [round(float(v), 3) for v in normalized]


def _run_separation(
    audio_48k: np.ndarray,
    model_name: str,
    device: torch.device,
    progress_cb: Optional[Callable[[str, int], None]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """選択されたモデル（UVR MDX-Net または Demucs）に応じて音源分離を実行する。"""
    if model_name.startswith("uvr_mdx_net"):
        from app.mdx_net_engine import separate_with_mdx_net
        return separate_with_mdx_net(audio_48k, model_name=model_name, device=device, progress_cb=progress_cb)
    return _separate_with_hdemucs(audio_48k, device=device, progress_cb=progress_cb)


def separate_audio(
    session_dir: Path,
    mode: str = "vocal_extract",
    model_name: str = "uvr_mdx_net_inst_hq_5",
    strength: int = 85,
    progress_cb: Optional[Callable[[str, int], None]] = None,
) -> Dict[str, Any]:
    """
    指定モードで音声分離・ノイズ除去を実行し、マスター(32bit float)およびプレビュー用(16bit PCM) WAVを書き出す。
    """
    if progress_cb:
        progress_cb("分離モデルの準備中...", 5)

    orig_wav = session_dir / "original_48k.wav"
    if not orig_wav.exists():
        raise FileNotFoundError("抽出済みの元音声ファイルが見つかりません。")

    audio_48k, sr = sf.read(str(orig_wav), dtype="float32", always_2d=True)
    if sr != TARGET_SR:
        raise ValueError(f"想定外のサンプルレートです: {sr}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if mode == "noise_reduce":
        if progress_cb:
            progress_cb("STFT定常ノイズ除去中...", 30)
        track_a, track_b = apply_spectral_noise_reduction(audio_48k, strength=strength)
        if progress_cb:
            progress_cb("ノイズ除去完了", 85)
    elif mode == "both":
        vocals, bgm = _run_separation(audio_48k, model_name=model_name, device=device, progress_cb=progress_cb)
        if progress_cb:
            progress_cb("STFT定常ノイズ除去中...", 82)
        # 分離後の声に残った定常ノイズを追加除去し、除去ノイズをトラックB側へ加算
        vocals_clean, removed_noise = apply_spectral_noise_reduction(vocals, strength=strength)
        track_a = vocals_clean
        track_b = bgm + removed_noise
        if progress_cb:
            progress_cb("ノイズ除去完了", 90)
    else:
        # vocal_extract (既定)
        vocals, bgm = _run_separation(audio_48k, model_name=model_name, device=device, progress_cb=progress_cb)
        strength_ratio = max(0.0, min(1.0, float(strength) / 100.0))
        # strengthが100%未満の場合、背景音成分をわずかに自然残存させるオプション調整
        bleed = (1.0 - strength_ratio) * 0.35
        track_a = vocals + bgm * bleed
        track_b = bgm * (1.0 - bleed)

    if progress_cb:
        progress_cb("マスターWAV保存 ＆ 波形解析中...", 92)

    # 波形保護のため -1.0〜1.0 に収めるのはプレビュー16bit用のみとし、マスターはfloat32で精密保持
    track_a_master = session_dir / "track_a_master.wav"
    track_b_master = session_dir / "track_b_master.wav"
    track_a_preview = session_dir / "track_a_preview.wav"
    track_b_preview = session_dir / "track_b_preview.wav"

    sf.write(str(track_a_master), track_a, TARGET_SR, subtype="FLOAT")
    sf.write(str(track_b_master), track_b, TARGET_SR, subtype="FLOAT")

    sf.write(str(track_a_preview), np.clip(track_a, -1.0, 1.0), TARGET_SR, subtype="PCM_16")
    sf.write(str(track_b_preview), np.clip(track_b, -1.0, 1.0), TARGET_SR, subtype="PCM_16")

    duration = float(audio_48k.shape[0]) / float(TARGET_SR)
    peaks_a = compute_waveform_peaks(track_a)
    peaks_b = compute_waveform_peaks(track_b)

    if progress_cb:
        progress_cb("完了", 100)

    return {
        "duration": round(duration, 3),
        "device_used": str(device),
        "mode": mode,
        "model_name": model_name,
        "strength": int(strength),
        "track_a_file": track_a_preview.name,
        "track_b_file": track_b_preview.name,
        "peaks_a": peaks_a,
        "peaks_b": peaks_b,
    }
