"""
リアルタイム進捗・非同期ジョブ管理モジュール (app/job_manager.py)
音声分離や文字起こしなどのGPU重処理を非同期ワーカーで実行し、
フロントエンドからのポーリングに対してステージ詳細、パーセント、経過時間を返す。
"""

import time
import uuid
from typing import Any, Callable, Dict, Optional


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def create_job(self, task_type: str) -> str:
        self.clean_old_jobs()
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        self._jobs[job_id] = {
            "job_id": job_id,
            "task_type": task_type,
            "status": "running",
            "percent": 0,
            "stage": "準備中...",
            "error": None,
            "result": None,
            "start_time": now,
            "updated_time": now,
        }
        return job_id

    def update(self, job_id: str, stage: str, percent: int) -> None:
        if job_id in self._jobs:
            self._jobs[job_id]["stage"] = stage
            self._jobs[job_id]["percent"] = max(0, min(99, int(percent)))
            self._jobs[job_id]["updated_time"] = time.time()

    def complete(self, job_id: str, result: Dict[str, Any]) -> None:
        if job_id in self._jobs:
            self._jobs[job_id]["status"] = "completed"
            self._jobs[job_id]["percent"] = 100
            self._jobs[job_id]["stage"] = "完了"
            self._jobs[job_id]["result"] = result
            self._jobs[job_id]["updated_time"] = time.time()

    def fail(self, job_id: str, error_message: str) -> None:
        if job_id in self._jobs:
            self._jobs[job_id]["status"] = "failed"
            self._jobs[job_id]["stage"] = "エラーが発生しました"
            self._jobs[job_id]["error"] = str(error_message)
            self._jobs[job_id]["updated_time"] = time.time()

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = time.time()
        elapsed = round(now - float(job["start_time"]), 1)
        return {
            "job_id": job["job_id"],
            "task_type": job["task_type"],
            "status": job["status"],
            "percent": int(job["percent"]),
            "stage": str(job["stage"]),
            "error": job["error"],
            "result": job["result"],
            "elapsed_sec": elapsed,
        }

    def clean_old_jobs(self, max_age_sec: float = 3600) -> None:
        now = time.time()
        expired = [
            jid for jid, info in self._jobs.items()
            if (now - float(info.get("start_time", now))) > max_age_sec
        ]
        for jid in expired:
            self._jobs.pop(jid, None)


job_manager = JobManager()
