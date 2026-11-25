# Changelog

All notable changes to **Voice Extractor & Transcriber WebUI** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-11-26 (Development Preview / 初回公開版)

ローカルGPU（NVIDIA CUDA）を活用した動画・音声からの声抽出、定常ノイズ除去、映像同期リアルタイム試聴、オンデマンド文字起こし、無劣化動画・24bit WAV 書き出し機能を備えた開発中プレビュー版を初回公開。

### Added (主な機能・実装内容)
- **音声分離・ノイズ除去エンジン**
  - `UVR-MDX-NET-Inst_HQ_5`（`onnx2torch` による PyTorch GPU 推論・STFT/iSTFT オーバーラップ加算パイプライン）を標準分離モデルとして統合
  - `torchaudio` Hybrid Demucs (`hdemucs_high`) による4-Stem音源分離に対応
  - STFT スペクトルゲーティングによる環境・定常ノイズ除去モード、および分離＋ノイズ除去の併用モードを実装
  - バックグラウンドジョブ管理とページ内モーダルによるリアルタイム進捗プログレスバー表示
- **同期映像プレビュー ＆ Web Audio リアルタイムミキサー**
  - 動画ファイル入力時のミュート済み同期映像モニター表示（音声トラックA/Bおよびミックス試聴と同期再生・シーク）
  - トラックA（声）・トラックB（背景音/ノイズ）の Canvas 波形描画、クリックシーク、ミュート・ソロ再生、0%〜150% 音量バランススライダー（95〜105% スナップ吸着・100%クリックリセット対応）
- **オンデマンド文字起こし（ローカル推論）**
  - `faster-whisper` 優先（`openai-whisper` フォールバック）による Whisper `large-v3-turbo` ローカル推論（GPU VRAM 不足時は自動 CPU `int8` フォールバック対応）
  - 認識プロンプトプリセット 5種（笑い声・感情・相槌／吐息・喘ぎ・叫び／掛け声・アクション／標準会話／カスタム）と常時表示プロンプト編集欄
  - タイムスタンプ付与・SRT 字幕形式生成
  - Silero VAD 無音カット無効化オプション（短い掛け声・単発音の拾得精度向上）
- **保存・書き出し・設定永続化**
  - `IrodoriTTS` 方式の保存先ベースフォルダ＋プリフィックス変数展開（`%date%`, `%time%`, `%datetime%`, `%filename%`, `%mode%`）
  - 24bit/48kHz PCM WAV 出力（トラックA / トラックB / ミックス）、音声差し替え MP4 出力（映像無劣化コピー）、映像のみ無音 MP4 出力、TXT / SRT 出力、および同一タイムスタンプでの全ファイル一括保存ボタン
  - `config.json`（`defaults` / `saved` 2層構造）による各種設定・音量バランス・ミュート状態の永続化と出荷時初期値リセットボタン
  - `temp_preview/` の件数・容量可視化と手動一括削除／フォルダを開く機能
  - ライト / ダーク / システム自動追従テーマ切替、UIヘッダー上への `v0.1.0` バージョンバッジ表示
- **独立仮想環境・公開整備**
  - プロジェクト直下 `.venv` への専用仮想環境構築スクリプト（`setup_venv.bat`）の汎用化（`D:\Python312` 優先・システム Python フォールバック、キャッシュ・一時ディレクトリのプロジェクト内隔離、`onnx` / `onnx2torch` 同梱、`UVR-MDX-NET-Inst_HQ_5.onnx` 自動取得＋失敗時手動案内）
  - `static-ffmpeg` を導入し、システムに FFmpeg が未導入の環境でも専用 `.venv` 内へ FFmpeg / FFprobe を自動配備するフォールバックを実装（既存環境ではシステム FFmpeg を優先）
  - ワンクリックで `git pull` と `.venv` 依存パッケージ同期を行う `update.bat` を追加
  - `README.md`（出荷時初期値クリーン全体プレビュー・5ステップ個別パネル画像・動作要件・モデル解説・使い方）および `CHANGELOG.md` の整備

### Changed
- アプリケーションのバージョン番号を初回開発中プレビューとして `1.0.0`（内部仮値）から `0.1.0` へ変更。
- 出荷時初期設定（`SYSTEM_DEFAULT_CONFIG` / UI 初期選択）を、初回利用者向けに `output_dir: "outputs"`、認識プリセット先頭 `standard`（通常・標準会話）、プロンプト欄空欄へ変更。
- `.gitignore` に未使用見本 `config.example.json` を追加し、公開リポジトリから除外（設定初期値は `app/config_manager.py` で一元管理し、実行時の設定変更で `config.json` が自動生成される仕様を明文化）。