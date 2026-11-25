"""
MDX-Net 音声分離エンジンモジュール (app/mdx_net_engine.py)
UVR-MDX-NET-Inst_HQ_5 を onnx2torch で PyTorch nn.Module に変換し、
RTX 4090 GPU 上で STFT/iSTFT オーバーラップ加算による高音質音源分離を実行する。
"""

import math
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
import onnx
import torch
import torchaudio
from onnx2torch import convert

from app.paths import BASE_DIR, MODELS_DIR

TARGET_SR = 48000
MDX_SR = 44100

# モデル定義パラメータ
MDX_MODELS_DIR = MODELS_DIR / "mdx_net"

MODEL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "uvr_mdx_net_inst_hq_5": {
        "filename": "UVR-MDX-NET-Inst_HQ_5.onnx",
        "n_fft": 5120,
        "hop_length": 1024,
        "dim_f": 2560,
        "dim_t": 256,
        "compensate": 1.01,
        "primary_stem": "Instrumental",  # 出力がインストゥルメンタル
    }
}

_MDX_MODEL_CACHE: Dict[str, Any] = {}


def get_mdx_model(model_name: str, device: torch.device) -> Tuple[torch.nn.Module, Dict[str, Any]]:
    """ONNXモデルを onnx2torch で PyTorch モデルに変換し、GPU 上にシングルトンロードする。"""
    cache_key = f"{model_name}_{device}"
    if model_name not in MODEL_CONFIGS:
        raise ValueError(f"未知のMDX-Netモデルです: {model_name}")

    cfg = MODEL_CONFIGS[model_name]
    if cache_key not in _MDX_MODEL_CACHE:
        model_file = MDX_MODELS_DIR / cfg["filename"]
        if not model_file.exists():
            raise FileNotFoundError(f"MDX-Netモデルファイルが見つかりません: {model_file}")

        onnx_proto = onnx.load(str(model_file))
        torch_model = convert(onnx_proto).to(device)
        torch_model.eval()
        _MDX_MODEL_CACHE[cache_key] = torch_model

    return _MDX_MODEL_CACHE[cache_key], cfg


def separate_with_mdx_net(
    audio_48k: np.ndarray,
    model_name: str = "uvr_mdx_net_inst_hq_5",
    device: Optional[torch.device] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    MDX-Net (Inst HQ 5) を用いて音声分離を実行し、
    (vocals_48k, inst_48k) を [samples, channels] 形式の 48kHz numpy 配列で返す。
    """
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if progress_cb:
        progress_cb("MDX-Net Inst HQ 5 モデル準備中...", 10)

    model, cfg = get_mdx_model(model_name, device)

    n_fft: int = cfg["n_fft"]
    hop_length: int = cfg["hop_length"]
    dim_f: int = cfg["dim_f"]
    dim_t: int = cfg["dim_t"]
    compensate: float = cfg["compensate"]

    orig_len = audio_48k.shape[0]

    # [samples, channels] -> [channels, samples]
    waveform_48k = torch.from_numpy(audio_48k.T).float()
    waveform_44k = torchaudio.functional.resample(waveform_48k, TARGET_SR, MDX_SR)
    total_samples = waveform_44k.shape[1]
    mix_44k_np = waveform_44k.numpy()

    chunk_samples = (dim_t - 1) * hop_length
    overlap_ratio = 0.5
    step_samples = int(chunk_samples * (1.0 - overlap_ratio))

    # パディング（反射モード）
    pad_len = chunk_samples
    padded_audio = np.pad(mix_44k_np, ((0, 0), (pad_len, pad_len + chunk_samples)), mode="reflect")
    total_padded = padded_audio.shape[1]

    output_padded = np.zeros_like(padded_audio)
    weight_padded = np.zeros(total_padded, dtype=np.float32)

    window_stft = torch.hann_window(n_fft).to(device)
    blend_window = np.hanning(chunk_samples).astype(np.float32)

    total_chunks = max(1, math.ceil((total_padded - chunk_samples) / step_samples))
    processed_chunks = 0

    start = 0
    with torch.no_grad():
        while start + chunk_samples <= total_padded:
            chunk_np = padded_audio[:, start : start + chunk_samples]
            chunk_tensor = torch.from_numpy(chunk_np).to(device)

            # STFT
            stft = torch.stft(
                chunk_tensor,
                n_fft=n_fft,
                hop_length=hop_length,
                window=window_stft,
                center=True,
                return_complex=True,
            )
            # [channels, dim_f, dim_t, 2]
            stft_real = torch.view_as_real(stft[:, :dim_f, :])
            # [1, 4, dim_f, dim_t] に変換
            spec_input = stft_real.permute(0, 3, 1, 2).reshape(1, 4, dim_f, dim_t)

            # 推論
            out_spec = model(spec_input) * compensate

            # iSTFT 用に整形
            out_spec = out_spec.reshape(2, 2, dim_f, dim_t).permute(0, 2, 3, 1)
            pad_nyquist = torch.zeros(2, 1, dim_t, 2, device=device)
            out_spec_padded = torch.cat([out_spec, pad_nyquist], dim=1)
            complex_spec = torch.view_as_complex(out_spec_padded)

            inv_chunk = torch.istft(
                complex_spec,
                n_fft=n_fft,
                hop_length=hop_length,
                window=window_stft,
                center=True,
                length=chunk_samples,
            )
            inv_np = inv_chunk.cpu().numpy()

            output_padded[:, start : start + chunk_samples] += inv_np * blend_window
            weight_padded[start : start + chunk_samples] += blend_window

            start += step_samples
            processed_chunks += 1

            if progress_cb:
                # 15% から 80% までの進捗率を均等配分
                pct = int(15 + (processed_chunks / total_chunks) * 65)
                progress_cb(f"MDX-Net 分離中 ({processed_chunks}/{total_chunks})...", pct)

    weight_safe = np.where(weight_padded < 1e-4, 1.0, weight_padded)
    output_padded /= weight_safe
    inst_44k_np = output_padded[:, pad_len : pad_len + total_samples]

    # primary_stem が Instrumental なので、ボーカルは差分 (Mix - Inst)
    vocals_44k_np = mix_44k_np - inst_44k_np

    if progress_cb:
        progress_cb("48kHz 高音質リサンプリング中...", 85)

    # 48kHz へリサンプリングして元の長さに一致させる
    inst_44k_t = torch.from_numpy(inst_44k_np).float()
    vocals_44k_t = torch.from_numpy(vocals_44k_np).float()

    inst_48k = torchaudio.functional.resample(inst_44k_t, MDX_SR, TARGET_SR).T.numpy()
    vocals_48k = torchaudio.functional.resample(vocals_44k_t, MDX_SR, TARGET_SR).T.numpy()

    return _match_length(vocals_48k, orig_len), _match_length(inst_48k, orig_len)


def _match_length(arr: np.ndarray, target_len: int) -> np.ndarray:
    """リサンプリングによる端数サンプル長を元の長さに厳密に一致させる。"""
    curr = arr.shape[0]
    if curr == target_len:
        return arr
    if curr > target_len:
        return arr[:target_len]
    pad = np.zeros((target_len - curr, arr.shape[1]), dtype=arr.dtype)
    return np.vstack([arr, pad])
