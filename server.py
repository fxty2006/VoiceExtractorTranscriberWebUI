"""
Voice Extractor & Transcriber WebUI（音声分離・文字起こしWebUI）: 起動エントリーポイント (server.py)
最初に app.paths で Cドライブ書き込み遮断の環境変数を確定させた上で、
FastAPI アプリケーションと uvicorn サーバーを起動する。
"""

import argparse
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# 最優先でDドライブ集約環境変数を適用
from app.paths import STATIC_DIR, enforce_d_drive_env, ensure_directories

enforce_d_drive_env()
ensure_directories()

from app.api_routes import router as api_router


def create_app() -> FastAPI:
    """FastAPIアプリケーションを生成し、ルーターと静的ファイルをマウントする。"""
    app = FastAPI(
        title="Voice Extractor & Transcriber WebUI（音声分離・文字起こしWebUI）",
        description="ローカルGPUを用いた音声分離・ノイズ除去・文字起こし・無劣化動画書き出しツール",
        version="0.1.0",
    )
    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Voice Extractor & Transcriber WebUI Server")
    parser.add_argument("--host", default="127.0.0.1", help="バインドホスト (既定: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7865, help="待受ポート (既定: 7865)")
    args = parser.parse_args()

    print(f"[Server] Starting Voice Extractor & Transcriber WebUI at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
