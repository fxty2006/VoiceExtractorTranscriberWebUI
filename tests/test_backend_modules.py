"""
Voice & Text Extractor WebUI バックエンド単体・結合テスト (tests/test_backend_modules.py)
すべてのテスト一時ファイルは Dドライブ本ディレクトリ配下の .cache/_unit_test_tmp に閉じ込め、
Cドライブへの書き込みゼロ・24bit/48kHz WAV・無劣化MP4差し替え・映像のみMP4・Temp管理を検証する。
"""

import json
import shutil
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import config_manager, media_exporter, paths, prefix_resolver, temp_manager
from app.audio_separator import (
    apply_spectral_noise_reduction,
    compute_waveform_peaks,
    prepare_session_media,
    probe_media_info,
    separate_audio,
)
from app.transcriber import segments_to_srt, segments_to_text, transcribe_audio


class TestVoiceTextExtractorBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        paths.enforce_d_drive_env()
        cls.work_root = paths.BASE_DIR / ".cache" / "_unit_test_tmp"
        if cls.work_root.exists():
            shutil.rmtree(cls.work_root, ignore_errors=True)
        cls.work_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.work_root.exists():
            shutil.rmtree(cls.work_root, ignore_errors=True)

    def test_01_d_drive_env_isolation(self) -> None:
        """Cドライブへのキャッシュ・一時ファイル遮断環境変数がすべて本プロジェクト配下であること。"""
        import os

        paths.enforce_d_drive_env()
        base_str = str(paths.BASE_DIR)
        for key in (
            "PIP_CACHE_DIR",
            "TORCH_HOME",
            "HF_HOME",
            "HUGGINGFACE_HUB_CACHE",
            "XDG_CACHE_HOME",
            "TEMP",
            "TMP",
            "GRADIO_TEMP_DIR",
        ):
            val = os.environ.get(key, "")
            self.assertTrue(val.startswith(base_str), f"{key} がプロジェクト配下ではありません: {val}")
            self.assertFalse(val.upper().startswith("C:"), f"{key} がCドライブを指しています: {val}")

    def test_02_config_manager_two_layer(self) -> None:
        """defaults / saved 2層JSON設定の保存と復元が動作すること。"""
        orig_cfg = config_manager.CONFIG_PATH
        test_cfg = self.work_root / "test_config.json"
        config_manager.CONFIG_PATH = test_cfg
        try:
            saved = config_manager.save_config({"strength": 60, "wav_target": "mixed"})
            self.assertEqual(saved["strength"], 60)
            self.assertEqual(saved["wav_target"], "mixed")

            raw = json.loads(test_cfg.read_text(encoding="utf-8"))
            self.assertIn("defaults", raw)
            self.assertIn("saved", raw)
            self.assertEqual(raw["defaults"]["strength"], 85)
            self.assertEqual(raw["saved"]["strength"], 60)

            loaded = config_manager.load_saved_config()
            self.assertEqual(loaded["strength"], 60)

            reset = config_manager.reset_to_defaults()
            self.assertEqual(reset["strength"], 85)
            self.assertEqual(reset["output_dir"], "outputs")
            self.assertEqual(reset["slider_vol_a"], 100)
            self.assertEqual(reset["slider_vol_b"], 100)
            self.assertEqual(reset["prompt_preset"], "standard")
            self.assertEqual(reset["custom_prompt"], "")
            loaded2 = config_manager.load_saved_config()
            self.assertEqual(loaded2["strength"], 85)
        finally:
            config_manager.CONFIG_PATH = orig_cfg

    def test_03_prefix_resolver_macros_and_uniqueness(self) -> None:
        """IrodoriTTS方式マクロ展開と危険文字無害化・連番衝突回避が機能すること。"""
        dt = datetime(2026, 11, 16, 9, 5, 3)
        out_root = self.work_root / "prefix_out"
        p1 = prefix_resolver.resolve_output_path(
            output_dir_raw=str(out_root),
            pattern_raw=r"%date%\%time%_%filename%_%mode%",
            original_filename="my:bad*name?.mp4",
            mode="vocal_extract",
            suffix_with_ext="_vocal.wav",
            now=dt,
            ensure_unique=True,
        )
        self.assertTrue(str(p1).endswith(r"2026-11-16\09-05-03_my_bad_name_vocal_extract_vocal.wav"))

        p1.parent.mkdir(parents=True, exist_ok=True)
        p1.write_bytes(b"dummy")
        p2 = prefix_resolver.resolve_output_path(
            output_dir_raw=str(out_root),
            pattern_raw=r"%date%\%time%_%filename%_%mode%",
            original_filename="my:bad*name?.mp4",
            mode="vocal_extract",
            suffix_with_ext="_vocal.wav",
            now=dt,
            ensure_unique=True,
        )
        self.assertEqual(p2.name, "09-05-03_my_bad_name_vocal_extract_vocal_001.wav")

    def test_04_temp_manager_manual_cleanup(self) -> None:
        """Tempフォルダ蓄積件数検知と現在セッション保護付き手動削除が動作すること。"""
        orig_temp = temp_manager.TEMP_PREVIEW_DIR
        test_temp = self.work_root / "temp_preview_mock"
        temp_manager.TEMP_PREVIEW_DIR = test_temp
        try:
            old_sess = test_temp / "old_session_01"
            cur_sess = test_temp / "cur_session_02"
            old_sess.mkdir(parents=True, exist_ok=True)
            cur_sess.mkdir(parents=True, exist_ok=True)
            (old_sess / "a.wav").write_bytes(b"0" * 1024)
            (cur_sess / "b.wav").write_bytes(b"1" * 2048)

            st = temp_manager.get_temp_status(exclude_session_id="cur_session_02")
            self.assertTrue(st["has_past_files"])
            self.assertEqual(st["past_files"], 1)
            self.assertIn("Tempフォルダに過去のプレビューが貯まっています", st["alert_text"])

            cleared = temp_manager.clear_temp_preview(exclude_session_id="cur_session_02")
            self.assertEqual(cleared["deleted_count"], 1)
            self.assertFalse(old_sess.exists())
            self.assertTrue(cur_sess.exists())
            self.assertFalse(cleared["has_past_files"])
            self.assertTrue(cleared["has_any_files"])
        finally:
            temp_manager.TEMP_PREVIEW_DIR = orig_temp

    def test_05_transcriber_formatting(self) -> None:
        """文字起こしセグメントから通常テキスト・タイムスタンプ・SRTが正しく整形されること。"""
        segs = [
            {"start": 0.0, "end": 2.345, "text": "テスト発話です。"},
            {"start": 3.0, "end": 5.5, "text": "音声抽出に成功しました。"},
        ]
        plain = segments_to_text(segs, use_timestamps=False)
        ts_txt = segments_to_text(segs, use_timestamps=True)
        srt = segments_to_srt(segs)

        self.assertEqual(plain, "テスト発話です。\n音声抽出に成功しました。")
        self.assertIn("[00:00.00 --> 00:02.35] テスト発話です。", ts_txt)
        self.assertIn("1\n00:00:00,000 --> 00:00:02,345\nテスト発話です。", srt)

        # ミキサーゲイン（ミュート・ソロ・150%上限）
        self.assertEqual(media_exporter.compute_effective_gains(120, 50, False, False, False, False), (1.2, 0.5))
        self.assertEqual(media_exporter.compute_effective_gains(120, 50, True, False, False, False), (0.0, 0.5))
        self.assertEqual(media_exporter.compute_effective_gains(120, 50, False, False, True, False), (1.2, 0.0))
        self.assertEqual(media_exporter.compute_effective_gains(200, -10, False, False, False, False), (1.5, 0.0))

    def test_06_noise_reduction_and_peaks(self) -> None:
        """STFTスペクトルゲーティングがノイズを抑制し、140ビンの波形ピークを返すこと。"""
        rng = np.random.default_rng(42)
        sr = 48000
        t = np.linspace(0, 1.5, int(sr * 1.5), endpoint=False)
        voice = 0.4 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
        noise = (0.04 * rng.standard_normal(len(t))).astype(np.float32)
        stereo = np.stack([voice + noise, voice + noise], axis=1)

        cleaned, removed = apply_spectral_noise_reduction(stereo, strength=85)
        self.assertEqual(cleaned.shape, stereo.shape)
        self.assertEqual(removed.shape, stereo.shape)
        self.assertGreater(float(np.mean(np.abs(removed))), 0.001)

        peaks = compute_waveform_peaks(cleaned, num_bins=140)
        self.assertEqual(len(peaks), 140)
        self.assertTrue(all(0.05 <= p <= 1.0 for p in peaks))

    def test_07_end_to_end_media_prepare_separate_and_export(self) -> None:
        """
        ffmpegで合成MP4を生成し、音声分離・24bit/48kHz WAV出力・無劣化MP4差し替え・映像のみMP4出力を一貫検証する。
        """
        ffmpeg_bin = paths.resolve_ffmpeg()
        ffprobe_bin = paths.resolve_ffprobe()
        self.assertIsNotNone(ffprobe_bin, "ffprobe が見つかりません")

        synth_mp4 = self.work_root / "synth_input.mp4"
        cmd_gen = [
            ffmpeg_bin,
            "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1.5:r=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            str(synth_mp4),
        ]
        proc = subprocess.run(cmd_gen, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"合成MP4作成失敗: {proc.stderr}")

        session_dir = self.work_root / "session_e2e"
        session_dir.mkdir(parents=True, exist_ok=True)
        meta = prepare_session_media(synth_mp4, session_dir)
        self.assertTrue(meta["has_video"])
        self.assertGreater(meta["duration"], 1.0)
        self.assertTrue((session_dir / "original_48k.wav").exists())
        self.assertTrue((session_dir / "video_preview.mp4").exists())

        # 映像プレビューが無音（音声なし）であること
        preview_info = probe_media_info(session_dir / "video_preview.mp4")
        self.assertTrue(preview_info["has_video"])
        self.assertFalse(preview_info["has_audio"])

        # 定常ノイズ除去モードで分離（ネットワーク依存なしで実行）
        sep_res = separate_audio(session_dir, mode="noise_reduce", strength=85)
        self.assertEqual(len(sep_res["peaks_a"]), 140)
        self.assertTrue((session_dir / "track_a_master.wav").exists())
        self.assertTrue((session_dir / "track_a_preview.wav").exists())

        # faster-whisper（Dドライブローカルモデル）オンデマンド文字起こし結合テスト
        tr_res = transcribe_audio(
            session_dir / "track_a_preview.wav",
            language="ja",
            use_timestamps=True,
            prompt_preset="laughter_emotion",
        )
        self.assertEqual(tr_res["engine"], "faster-whisper")
        self.assertIn("segments", tr_res)

        export_dir = self.work_root / "exported"

        # 1. 24bit/48kHz WAV 書き出し（両トラック）
        wav_paths = media_exporter.export_adjusted_wav(
            session_dir=session_dir,
            output_dir=str(export_dir),
            filename_pattern="%filename%",
            original_filename="synth_input.mp4",
            mode="noise_reduce",
            wav_target="both",
            vol_a_pct=120.0,
            vol_b_pct=50.0,
        )
        self.assertEqual(len(wav_paths), 2)
        for wp in wav_paths:
            info = sf.info(wp)
            self.assertEqual(info.samplerate, 48000)
            self.assertEqual(info.subtype, "PCM_24")

        # 2. 映像無劣化・音声差し替えMP4書き出し
        rep_mp4 = media_exporter.export_replaced_mp4(
            session_dir=session_dir,
            source_video_path=synth_mp4,
            output_dir=str(export_dir),
            filename_pattern="%filename%",
            original_filename="synth_input.mp4",
            mode="noise_reduce",
            wav_target="mixed",
            vol_a_pct=100.0,
            vol_b_pct=20.0,
        )
        rep_info = probe_media_info(Path(rep_mp4))
        self.assertTrue(rep_info["has_video"])
        self.assertTrue(rep_info["has_audio"])

        # 3. 映像のみ（音声完全除去）MP4書き出し
        vo_mp4 = media_exporter.export_video_only_mp4(
            source_video_path=synth_mp4,
            output_dir=str(export_dir),
            filename_pattern="%filename%",
            original_filename="synth_input.mp4",
            mode="noise_reduce",
        )
        vo_info = probe_media_info(Path(vo_mp4))
        self.assertTrue(vo_info["has_video"])
        self.assertFalse(vo_info["has_audio"])

        # 4. 文字起こしテキスト & SRT 保存
        txt_paths = media_exporter.export_transcript_files(
            output_dir=str(export_dir),
            filename_pattern="%filename%",
            original_filename="synth_input.mp4",
            mode="noise_reduce",
            text_content="[00:00.00 --> 00:01.50] テストテキスト",
            srt_content="1\n00:00:00,000 --> 00:00:01,500\nテストテキスト\n",
        )
        self.assertEqual(len(txt_paths), 2)
        self.assertTrue(Path(txt_paths[0]).exists())
        self.assertTrue(Path(txt_paths[1]).exists())

    def test_08_job_manager_lifecycle(self):
        """リアルタイム進捗ジョブ管理のライフサイクル（作成・更新・完了・失敗）を検証する。"""
        from app.job_manager import JobManager

        jm = JobManager()
        jid = jm.create_job("separate")
        job = jm.get(jid)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["percent"], 0)

        # 途中進捗の更新
        jm.update(jid, "Demucs分離中 (3/10)", 30)
        job = jm.get(jid)
        self.assertEqual(job["percent"], 30)
        self.assertIn("Demucs分離中", job["stage"])

        # 完了時
        jm.complete(jid, {"success": True, "output": "ok"})
        job = jm.get(jid)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["percent"], 100)
        self.assertEqual(job["result"]["output"], "ok")

        # 失敗ジョブの検証
        jid2 = jm.create_job("transcribe")
        jm.fail(jid2, "モデル読み込みエラー")
        job2 = jm.get(jid2)
        self.assertEqual(job2["status"], "failed")
        self.assertIn("モデル読み込みエラー", job2["error"])

    def test_09_export_all_atomic(self):
        """全成果物を同一タイムスタンプでアトミックに一括書き出しできることを検証する。"""
        from app.media_exporter import export_all_media

        session_dir = Path(self.work_root) / "session_export_all"
        session_dir.mkdir(parents=True, exist_ok=True)
        export_dir = Path(self.work_root) / "export_all_out"
        export_dir.mkdir(parents=True, exist_ok=True)

        sr = 48000
        t = np.linspace(0, 1.0, sr, endpoint=False)
        audio_a = (np.sin(2 * np.pi * 440 * t) * 0.4).astype(np.float32)
        audio_b = (np.sin(2 * np.pi * 880 * t) * 0.2).astype(np.float32)
        sf.write(str(session_dir / "track_a_master.wav"), audio_a, sr, subtype="FLOAT")
        sf.write(str(session_dir / "track_b_master.wav"), audio_b, sr, subtype="FLOAT")

        saved = export_all_media(
            session_dir=session_dir,
            output_dir=str(export_dir),
            filename_pattern="%date%\\%time%_%filename%",
            original_filename="sample_audio.wav",
            mode="vocal_extract",
            has_video=False,
            source_video_path=None,
            text_content="[00:00.00 --> 00:01.00] テスト",
            srt_content="1\n00:00:00,000 --> 00:00:01,000\nテスト\n",
        )
        self.assertEqual(len(saved), 4)
        parent_dirs = set(Path(p).parent for p in saved)
        self.assertEqual(len(parent_dirs), 1, "全ファイルが同一タイムスタンプフォルダに出力されていること")
        for p in saved:
            self.assertTrue(Path(p).exists())

    def test_10_mdx_net_inst_hq_5_separation(self):
        """UVR-MDX-NET-Inst_HQ_5 を用いた48kHz音声分離パイプラインの正常動作を検証する。"""
        import torch
        from app.mdx_net_engine import separate_with_mdx_net

        sr = 48000
        duration = 1.0
        total_samples = int(sr * duration)
        t = np.linspace(0, duration, total_samples, endpoint=False)
        # ステレオ波形 [samples, 2]
        mix = np.stack([
            (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32),
            (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
        ], axis=1)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        vocals_48k, inst_48k = separate_with_mdx_net(mix, model_name="uvr_mdx_net_inst_hq_5", device=device)

        self.assertEqual(vocals_48k.shape, mix.shape)
        self.assertEqual(inst_48k.shape, mix.shape)
        self.assertFalse(np.isnan(vocals_48k).any())
        self.assertFalse(np.isnan(inst_48k).any())

    def test_11_transcribe_disable_vad_and_action_shouts(self) -> None:
        """disable_vad=True および action_shouts プリセット指定で文字起こしパイプラインが正常完走することを検証する。"""
        from app.transcriber import PROMPT_PRESETS

        self.assertIn("action_shouts", PROMPT_PRESETS)
        self.assertFalse(PROMPT_PRESETS["action_shouts"]["use_vad"])
        self.assertIn("disable_vad", config_manager.SYSTEM_DEFAULT_CONFIG)
        self.assertFalse(config_manager.SYSTEM_DEFAULT_CONFIG["disable_vad"])

        sr = 48000
        duration = 1.0
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        sig = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        stereo = np.stack([sig, sig], axis=1)
        wav_path = self.work_root / "test_action_shouts.wav"
        sf.write(str(wav_path), stereo, sr, subtype="PCM_16")

        res = transcribe_audio(
            wav_path,
            language="ja",
            use_timestamps=True,
            disable_vad=True,
            prompt_preset="action_shouts",
        )
        self.assertEqual(res["engine"], "faster-whisper")
        self.assertIn("segments", res)
        self.assertIsInstance(res["segments"], list)

    def test_12_config_mute_state_persistence(self) -> None:
        """トラックA/Bのミュート状態（mute_a / mute_b）の保存・復元・初期化が動作すること。"""
        self.assertIn("mute_a", config_manager.SYSTEM_DEFAULT_CONFIG)
        self.assertIn("mute_b", config_manager.SYSTEM_DEFAULT_CONFIG)
        self.assertFalse(config_manager.SYSTEM_DEFAULT_CONFIG["mute_a"])
        self.assertFalse(config_manager.SYSTEM_DEFAULT_CONFIG["mute_b"])

        orig_cfg = config_manager.CONFIG_PATH
        test_cfg = self.work_root / "test_mute_config.json"
        config_manager.CONFIG_PATH = test_cfg
        try:
            saved = config_manager.save_config({"mute_a": True, "mute_b": False, "slider_vol_b": 70})
            self.assertTrue(saved["mute_a"])
            self.assertFalse(saved["mute_b"])
            self.assertEqual(saved["slider_vol_b"], 70)

            loaded = config_manager.load_saved_config()
            self.assertTrue(loaded["mute_a"])
            self.assertFalse(loaded["mute_b"])
            self.assertEqual(loaded["slider_vol_b"], 70)

            reset = config_manager.reset_to_defaults()
            self.assertFalse(reset["mute_a"])
            self.assertFalse(reset["mute_b"])
            self.assertEqual(reset["slider_vol_b"], 100)
        finally:
            config_manager.CONFIG_PATH = orig_cfg


if __name__ == "__main__":
    unittest.main(verbosity=2)