"""
FastAPI REST API ルーターモジュール (app/api_routes.py)
フロントエンドからのファイルアップロード、分離実行、文字起こし、明示的保存、
Temp管理、設定管理、およびメディアファイル配信（HTTP Range対応）を仲介する。
"""

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import torch
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.audio_separator import prepare_session_media, separate_audio
from app.config_manager import load_defaults, load_saved_config, reset_to_defaults, save_config, select_output_dir
from app.job_manager import job_manager
from app.media_exporter import (
    export_adjusted_wav,
    export_all_media,
    export_replaced_mp4,
    export_transcript_files,
    export_video_only_mp4,
)
from app.paths import (
    STATIC_DIR,
    TEMP_PREVIEW_DIR,
    is_supported_extension,
    resolve_ffmpeg,
)
from app.prefix_resolver import resolve_output_dir, resolve_output_path
from app.temp_manager import clear_temp_preview, get_temp_status, open_temp_folder
from app.transcriber import transcribe_audio

router = APIRouter()


class SeparateRequest(BaseModel):
    session_id: str
    mode: str = "vocal_extract"
    model_name: str = "uvr_mdx_net_inst_hq_5"
    strength: int = 85


class TranscribeRequest(BaseModel):
    session_id: str
    language: str = "ja"
    use_timestamps: bool = True
    disable_vad: bool = False
    include_laughs: bool = False
    prompt_preset: str = "standard"
    custom_prompt: str = ""


class ExportBaseRequest(BaseModel):
    session_id: str
    output_dir: str = "outputs"
    filename_pattern: str = "%date%\\%time%_%filename%"
    wav_target: str = "vocal"
    vol_a_pct: float = 100.0
    vol_b_pct: float = 0.0
    mute_a: bool = False
    mute_b: bool = False
    solo_a: bool = False
    solo_b: bool = False


class ExportTranscriptRequest(BaseModel):
    session_id: str
    output_dir: str = "outputs"
    filename_pattern: str = "%date%\\%time%_%filename%"
    text_content: str
    srt_content: str = ""


class ExportAllRequest(BaseModel):
    session_id: str
    output_dir: str = "outputs"
    filename_pattern: str = "%date%\\%time%_%filename%"
    vol_a_pct: float = 100.0
    vol_b_pct: float = 100.0
    mute_a: bool = False
    mute_b: bool = False
    solo_a: bool = False
    solo_b: bool = False
    text_content: Optional[str] = None
    srt_content: Optional[str] = None


class OpenExportDirRequest(BaseModel):
    output_dir: str = "outputs"
    target_path: Optional[str] = None


class PreviewPathRequest(BaseModel):
    output_dir: str = "outputs"
    filename_pattern: str = "%date%\\%time%_%filename%"
    original_filename: str = "sample_video.mp4"
    mode: str = "vocal_extract"
    wav_target: str = "vocal"


class ConfigUpdateRequest(BaseModel):
    values: Dict[str, Any]


class SelectDirRequest(BaseModel):
    current_dir: str = ""


def _get_session_dir(session_id: str) -> Path:
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        raise HTTPException(status_code=400, detail="不正なセッションIDです。")
    s_dir = TEMP_PREVIEW_DIR / session_id
    if not s_dir.exists():
        raise HTTPException(status_code=404, detail="セッションが見つかりません。ファイルを再読み込みしてください。")
    return s_dir


def _load_session_meta(session_dir: Path) -> Dict[str, Any]:
    meta_path = session_dir / "session_meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="セッションメタ情報が見つかりません。")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _save_session_meta(session_dir: Path, meta: Dict[str, Any]) -> None:
    meta_path = session_dir / "session_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


@router.get("/")
async def serve_index() -> FileResponse:
    """メインWebUI HTMLを返す。"""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html が見つかりません。")
    return FileResponse(str(index_path))


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """ブラウザの自動favicon要求による404ログを抑止する。"""
    return Response(status_code=204)


@router.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """システム状態（GPU・ffmpeg・設定・Temp状態）を返す。"""
    try:
        ffmpeg_path = resolve_ffmpeg()
        ffmpeg_ok = True
    except RuntimeError:
        ffmpeg_path = ""
        ffmpeg_ok = False

    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU Mode"
    return {
        "status": "ok",
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": gpu_name,
        "ffmpeg_available": ffmpeg_ok,
        "ffmpeg_path": ffmpeg_path,
        "config": load_saved_config(),
        "defaults": load_defaults(),
        "temp_status": get_temp_status(),
    }


@router.get("/api/config")
async def get_config() -> Dict[str, Any]:
    return {"saved": load_saved_config(), "defaults": load_defaults()}


@router.post("/api/config")
async def update_config(req: ConfigUpdateRequest) -> Dict[str, Any]:
    saved = save_config(req.values)
    return {"saved": saved}


@router.post("/api/config/reset")
async def api_config_reset() -> Dict[str, Any]:
    """出荷時初期値（defaults）へ設定をリセットして返す。"""
    cleared = reset_to_defaults()
    return {"status": "ok", "saved": cleared, "defaults": load_defaults()}


@router.post("/api/config/select-dir")
async def api_select_dir(req: SelectDirRequest) -> Dict[str, Any]:
    chosen = select_output_dir(req.current_dir)
    return {"selected_dir": chosen}


@router.get("/api/temp/status")
async def api_temp_status(session_id: Optional[str] = None) -> Dict[str, Any]:
    return get_temp_status(exclude_session_id=session_id)


@router.post("/api/temp/clear")
async def api_temp_clear(session_id: Optional[str] = None) -> Dict[str, Any]:
    return clear_temp_preview(exclude_session_id=session_id)


@router.post("/api/temp/open")
async def api_temp_open() -> Dict[str, Any]:
    ok = open_temp_folder()
    return {"opened": ok}


@router.post("/api/preview-path")
async def api_preview_path(req: PreviewPathRequest) -> Dict[str, Any]:
    suffix_map = {
        "vocal": "_vocal.wav",
        "mixed": "_mixed.wav",
        "bgm": "_bgm.wav",
        "both": "_vocal.wav (+ _bgm.wav)",
    }
    suffix = suffix_map.get(req.wav_target, "_vocal.wav")
    base_sample = resolve_output_path(
        output_dir_raw=req.output_dir,
        pattern_raw=req.filename_pattern,
        original_filename=req.original_filename,
        mode=req.mode,
        suffix_with_ext=suffix,
        ensure_unique=False,
    )
    return {"preview_path": str(base_sample)}


@router.post("/api/upload")
async def api_upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    """動画または音声ファイルを受信し、一時作業セッションを作成して基本メタ情報を返す。"""
    orig_name = Path(file.filename or "input.wav").name
    if not is_supported_extension(orig_name):
        raise HTTPException(status_code=400, detail=f"未対応の拡張子です: {orig_name}")

    session_id = uuid.uuid4().hex[:12]
    session_dir = TEMP_PREVIEW_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(orig_name).suffix.lower()
    input_path = session_dir / f"source_input{ext}"

    try:
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_size = input_path.stat().st_size

        meta = prepare_session_media(input_path, session_dir)
        meta.update({
            "session_id": session_id,
            "original_filename": orig_name,
            "source_input_file": input_path.name,
            "file_size_bytes": file_size,
            "process_mode": "vocal_extract",
            "separated": False,
            "transcribed": False,
        })
        _save_session_meta(session_dir, meta)

        return {
            "session_id": session_id,
            "original_filename": orig_name,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "has_video": meta["has_video"],
            "duration": meta["duration"],
            "video_codec": meta.get("video_codec", ""),
            "audio_sr": meta.get("audio_sr", 0),
            "original_audio_url": f"/api/media/{session_id}/{meta['original_audio_file']}",
            "video_preview_url": (
                f"/api/media/{session_id}/{meta['video_preview_file']}"
                if meta.get("video_preview_file")
                else None
            ),
            "temp_status": get_temp_status(exclude_session_id=session_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"ファイル読込処理中にエラーが発生しました: {e}")


def _run_separate_job(job_id: str, req: SeparateRequest) -> None:
    try:
        session_dir = _get_session_dir(req.session_id)
        meta = _load_session_meta(session_dir)

        def _cb(stage: str, pct: int) -> None:
            job_manager.update(job_id, stage, pct)

        result = separate_audio(
            session_dir=session_dir,
            mode=req.mode,
            model_name=req.model_name,
            strength=req.strength,
            progress_cb=_cb,
        )
        meta["process_mode"] = req.mode
        meta["separated"] = True
        _save_session_meta(session_dir, meta)

        save_config({
            "process_mode": req.mode,
            "model_name": req.model_name,
            "strength": req.strength,
        })

        out = {
            "session_id": req.session_id,
            "duration": result["duration"],
            "device_used": result["device_used"],
            "has_video": meta["has_video"],
            "track_a_url": f"/api/media/{req.session_id}/{result['track_a_file']}?t={uuid.uuid4().hex[:6]}",
            "track_b_url": f"/api/media/{req.session_id}/{result['track_b_file']}?t={uuid.uuid4().hex[:6]}",
            "peaks_a": result["peaks_a"],
            "peaks_b": result["peaks_b"],
            "temp_status": get_temp_status(exclude_session_id=req.session_id),
        }
        job_manager.complete(job_id, out)
    except Exception as e:
        job_manager.fail(job_id, str(e))


def _run_transcribe_job(job_id: str, req: TranscribeRequest) -> None:
    try:
        session_dir = _get_session_dir(req.session_id)
        meta = _load_session_meta(session_dir)
        track_a = session_dir / "track_a_preview.wav"
        if not track_a.exists():
            raise FileNotFoundError("音声分離が未完了です。")

        def _cb(stage: str, pct: int) -> None:
            job_manager.update(job_id, stage, pct)

        res = transcribe_audio(
            track_a,
            language=req.language,
            use_timestamps=req.use_timestamps,
            disable_vad=req.disable_vad,
            include_laughs=req.include_laughs,
            prompt_preset=req.prompt_preset,
            custom_prompt=req.custom_prompt,
            progress_cb=_cb,
        )
        meta["transcribed"] = True
        _save_session_meta(session_dir, meta)
        save_config({
            "language": req.language,
            "use_timestamps": req.use_timestamps,
            "disable_vad": req.disable_vad,
            "include_laughs": req.include_laughs,
            "prompt_preset": req.prompt_preset,
            "custom_prompt": req.custom_prompt,
        })
        job_manager.complete(job_id, res)
    except Exception as e:
        job_manager.fail(job_id, str(e))


@router.post("/api/separate/start")
async def api_separate_start(req: SeparateRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """音声分離処理をバックグラウンドジョブとして開始し、ポーリング用job_idを返す。"""
    _get_session_dir(req.session_id)
    job_id = job_manager.create_job("separate")
    background_tasks.add_task(_run_separate_job, job_id, req)
    return {"job_id": job_id}


@router.post("/api/transcribe/start")
async def api_transcribe_start(req: TranscribeRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """文字起こし処理をバックグラウンドジョブとして開始し、ポーリング用job_idを返す。"""
    _get_session_dir(req.session_id)
    job_id = job_manager.create_job("transcribe")
    background_tasks.add_task(_run_transcribe_job, job_id, req)
    return {"job_id": job_id}


@router.get("/api/job/{job_id}")
async def api_get_job(job_id: str) -> Dict[str, Any]:
    """ジョブの進捗状態（percent, stage, elapsed_sec, result）を取得する。"""
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="指定されたジョブが見つかりません。")
    return job


@router.post("/api/separate")
async def api_separate(req: SeparateRequest) -> Dict[str, Any]:
    """音声分離・ノイズ除去を実行してプレビュー用WAVと波形データを返す。"""
    session_dir = _get_session_dir(req.session_id)
    meta = _load_session_meta(session_dir)

    try:
        result = separate_audio(
            session_dir=session_dir,
            mode=req.mode,
            model_name=req.model_name,
            strength=req.strength,
        )
        meta["process_mode"] = req.mode
        meta["separated"] = True
        _save_session_meta(session_dir, meta)

        save_config({
            "process_mode": req.mode,
            "model_name": req.model_name,
            "strength": req.strength,
        })

        return {
            "session_id": req.session_id,
            "duration": result["duration"],
            "device_used": result["device_used"],
            "has_video": meta["has_video"],
            "track_a_url": f"/api/media/{req.session_id}/{result['track_a_file']}?t={uuid.uuid4().hex[:6]}",
            "track_b_url": f"/api/media/{req.session_id}/{result['track_b_file']}?t={uuid.uuid4().hex[:6]}",
            "peaks_a": result["peaks_a"],
            "peaks_b": result["peaks_b"],
            "temp_status": get_temp_status(exclude_session_id=req.session_id),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"音声分離処理に失敗しました: {e}")


@router.post("/api/transcribe")
async def api_transcribe(req: TranscribeRequest) -> Dict[str, Any]:
    """トラックA（抽出された声）からオンデマンドで文字起こしを実行する。"""
    session_dir = _get_session_dir(req.session_id)
    meta = _load_session_meta(session_dir)
    track_a = session_dir / "track_a_preview.wav"
    if not track_a.exists():
        raise HTTPException(status_code=400, detail="音声分離が未完了です。")

    try:
        res = transcribe_audio(
            track_a,
            language=req.language,
            use_timestamps=req.use_timestamps,
            disable_vad=req.disable_vad,
            include_laughs=req.include_laughs,
            prompt_preset=req.prompt_preset,
            custom_prompt=req.custom_prompt,
        )
        meta["transcribed"] = True
        _save_session_meta(session_dir, meta)
        save_config({
            "language": req.language,
            "use_timestamps": req.use_timestamps,
            "disable_vad": req.disable_vad,
            "include_laughs": req.include_laughs,
            "prompt_preset": req.prompt_preset,
            "custom_prompt": req.custom_prompt,
        })
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文字起こし処理に失敗しました: {e}")


@router.post("/api/export/wav")
async def api_export_wav(req: ExportBaseRequest) -> Dict[str, Any]:
    """調整済み音声（24bit / 48kHz WAV）を本保存する。"""
    session_dir = _get_session_dir(req.session_id)
    meta = _load_session_meta(session_dir)
    try:
        saved = export_adjusted_wav(
            session_dir=session_dir,
            output_dir=req.output_dir,
            filename_pattern=req.filename_pattern,
            original_filename=meta["original_filename"],
            mode=meta.get("process_mode", "vocal_extract"),
            wav_target=req.wav_target,
            vol_a_pct=req.vol_a_pct,
            vol_b_pct=req.vol_b_pct,
            mute_a=req.mute_a,
            mute_b=req.mute_b,
            solo_a=req.solo_a,
            solo_b=req.solo_b,
        )
        save_config({
            "output_dir": req.output_dir,
            "filename_pattern": req.filename_pattern,
            "wav_target": req.wav_target,
        })
        return {"saved_paths": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WAV保存に失敗しました: {e}")


@router.post("/api/export/video-replaced")
async def api_export_video_replaced(req: ExportBaseRequest) -> Dict[str, Any]:
    """映像無劣化・音声差し替えMP4を本保存する。"""
    session_dir = _get_session_dir(req.session_id)
    meta = _load_session_meta(session_dir)
    if not meta.get("has_video"):
        raise HTTPException(status_code=400, detail="音声のみの入力ファイルには動画差し替えを行えません。")

    source_video = session_dir / meta["source_input_file"]
    try:
        out_path = export_replaced_mp4(
            session_dir=session_dir,
            source_video_path=source_video,
            output_dir=req.output_dir,
            filename_pattern=req.filename_pattern,
            original_filename=meta["original_filename"],
            mode=meta.get("process_mode", "vocal_extract"),
            wav_target=req.wav_target,
            vol_a_pct=req.vol_a_pct,
            vol_b_pct=req.vol_b_pct,
            mute_a=req.mute_a,
            mute_b=req.mute_b,
            solo_a=req.solo_a,
            solo_b=req.solo_b,
        )
        save_config({"output_dir": req.output_dir, "filename_pattern": req.filename_pattern})
        return {"saved_paths": [out_path]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"音声差し替えMP4保存に失敗しました: {e}")


@router.post("/api/export/video-only")
async def api_export_video_only(req: ExportBaseRequest) -> Dict[str, Any]:
    """映像のみ（音声完全除去・無劣化MP4）を本保存する。"""
    session_dir = _get_session_dir(req.session_id)
    meta = _load_session_meta(session_dir)
    if not meta.get("has_video"):
        raise HTTPException(status_code=400, detail="音声のみの入力ファイルには映像のみ保存を行えません。")

    source_video = session_dir / meta["source_input_file"]
    try:
        out_path = export_video_only_mp4(
            source_video_path=source_video,
            output_dir=req.output_dir,
            filename_pattern=req.filename_pattern,
            original_filename=meta["original_filename"],
            mode=meta.get("process_mode", "vocal_extract"),
        )
        save_config({"output_dir": req.output_dir, "filename_pattern": req.filename_pattern})
        return {"saved_paths": [out_path]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"映像のみMP4保存に失敗しました: {e}")


@router.post("/api/export/transcript")
async def api_export_transcript(req: ExportTranscriptRequest) -> Dict[str, Any]:
    """文字起こしテキスト (.txt) および SRT字幕 (.srt) を本保存する。"""
    session_dir = _get_session_dir(req.session_id)
    meta = _load_session_meta(session_dir)
    try:
        saved = export_transcript_files(
            output_dir=req.output_dir,
            filename_pattern=req.filename_pattern,
            original_filename=meta["original_filename"],
            mode=meta.get("process_mode", "vocal_extract"),
            text_content=req.text_content,
            srt_content=req.srt_content,
        )
        save_config({"output_dir": req.output_dir, "filename_pattern": req.filename_pattern})
        return {"saved_paths": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文字起こし保存に失敗しました: {e}")


@router.post("/api/export/all")
async def api_export_all(req: ExportAllRequest) -> Dict[str, Any]:
    """全成果物（WAV, MP4, TXT, SRT）を同一タイムスタンプで一括保存する。"""
    session_dir = _get_session_dir(req.session_id)
    meta = _load_session_meta(session_dir)
    source_video_path = session_dir / meta.get("source_input_file", "") if meta.get("has_video") else None
    try:
        saved = export_all_media(
            session_dir=session_dir,
            output_dir=req.output_dir,
            filename_pattern=req.filename_pattern,
            original_filename=meta["original_filename"],
            mode=meta.get("process_mode", "vocal_extract"),
            has_video=bool(meta.get("has_video")),
            source_video_path=source_video_path,
            vol_a_pct=req.vol_a_pct,
            vol_b_pct=req.vol_b_pct,
            mute_a=req.mute_a,
            mute_b=req.mute_b,
            solo_a=req.solo_a,
            solo_b=req.solo_b,
            text_content=req.text_content,
            srt_content=req.srt_content,
        )
        save_config({
            "output_dir": req.output_dir,
            "filename_pattern": req.filename_pattern,
        })
        return {"saved_paths": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"一括保存に失敗しました: {e}")


@router.post("/api/export/open")
async def api_export_open(req: OpenExportDirRequest) -> Dict[str, Any]:
    """指定された保存先フォルダ（または特定ファイルを含む親フォルダ）をエクスプローラーで開く。"""
    try:
        if req.target_path and Path(req.target_path).exists():
            target = Path(req.target_path)
            target_dir = target.parent if target.is_file() else target
        else:
            target_dir = resolve_output_dir(req.output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target_dir))
        return {"opened": True, "path": str(target_dir)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"フォルダを開けませんでした: {e}")


@router.get("/api/media/{session_id}/{filename}")
async def api_serve_media(session_id: str, filename: str) -> FileResponse:
    """プレビュー用音声・映像ファイルを配信する（FastAPI FileResponse により Range リクエスト標準対応）。"""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="不正なファイル名です。")
    session_dir = _get_session_dir(session_id)
    target = session_dir / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="メディアファイルが見つかりません。")
    return FileResponse(str(target))