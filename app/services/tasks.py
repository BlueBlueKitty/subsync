from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.models import CreateTaskRequest, TaskStatus, TaskSummary
from app.services.ffsubsync_runner import build_ffsubsync_command


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decode_output_line(line: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "cp936", "latin-1"):
        try:
            return line.decode(encoding)
        except UnicodeDecodeError:
            continue
    return line.decode("utf-8", errors="replace")


@dataclass
class TaskRecord:
    task_id: str
    request: CreateTaskRequest
    video_path: str
    subtitle_path: str
    output_path: str
    output_name: str
    source_type: str
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    progress: int = 0
    progress_message: str = "等待执行"
    can_download_output: bool = False
    working_directory: Optional[str] = None
    process: Optional[asyncio.subprocess.Process] = None
    cancelled: bool = False
    log_lines: list[str] = field(default_factory=list)

    def append_log(self, line: str) -> None:
        self.log_lines.append(line.rstrip("\r\n"))
        self._update_progress_from_log(line)

    def _update_progress_from_log(self, line: str) -> None:
        text = line.strip()
        if "extracting speech segments from reference" in text:
            self.progress = max(self.progress, 10)
            self.progress_message = "提取视频语音片段"
        elif "extracting speech segments from subtitles" in text:
            self.progress = max(self.progress, 35)
            self.progress_message = "解析字幕时间轴"
        elif "computing alignments" in text:
            self.progress = max(self.progress, 70)
            self.progress_message = "计算时间轴对齐"
        elif "writing output to" in text:
            self.progress = max(self.progress, 90)
            self.progress_message = "写入输出字幕"
        elif "100%|" in text:
            self.progress = max(self.progress, 55)
            if self.progress_message == "提取视频语音片段":
                self.progress_message = "语音提取完成"

    def log_text(self) -> str:
        return "\n".join(self.log_lines)

    def to_summary(self) -> TaskSummary:
        return TaskSummary(
            task_id=self.task_id,
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            video_path=self.video_path,
            subtitle_path=self.subtitle_path,
            output_path=self.output_path,
            output_name=self.output_name,
            progress=self.progress,
            progress_message=self.progress_message,
            source_type=self.source_type,
            can_download_output=self.can_download_output,
            error=self.error,
        )


class TaskManager:
    def __init__(self, max_concurrent_tasks: int) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._task_order: list[str] = []
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)

    async def create_task(
        self,
        request: CreateTaskRequest,
        video_path: Path,
        subtitle_path: Path,
        output_path: Path,
        source_type: str,
    ) -> TaskRecord:
        task_id = uuid4().hex
        record = TaskRecord(
            task_id=task_id,
            request=request,
            video_path=str(video_path),
            subtitle_path=str(subtitle_path),
            output_path=str(output_path),
            output_name=output_path.name,
            source_type=source_type,
            status=TaskStatus.QUEUED,
            created_at=_utc_now(),
            can_download_output=source_type == "upload",
            working_directory=str(output_path.parent),
        )
        async with self._lock:
            self._tasks[task_id] = record
            self._task_order.insert(0, task_id)
        asyncio.create_task(self._run_task(record, video_path, subtitle_path, output_path))
        return record

    async def get_task(self, task_id: str) -> TaskRecord:
        async with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    async def list_tasks(self) -> list[TaskRecord]:
        async with self._lock:
            return [self._tasks[task_id] for task_id in self._task_order]

    async def stop_task(self, task_id: str) -> TaskRecord:
        task = await self.get_task(task_id)
        if task.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
            return task
        task.cancelled = True
        task.progress_message = "正在终止任务"
        task.append_log("请求终止任务")
        if task.process is not None and task.process.returncode is None:
            task.process.terminate()
        else:
            task.status = TaskStatus.FAILED
            task.error = "任务已取消"
            task.finished_at = _utc_now()
            task.progress_message = "任务已取消"
        return task

    async def _run_task(
        self,
        record: TaskRecord,
        video_path: Path,
        subtitle_path: Path,
        output_path: Path,
    ) -> None:
        async with self._semaphore:
            record.status = TaskStatus.RUNNING
            record.started_at = _utc_now()
            record.progress = 5
            record.progress_message = "启动 ffsubsync"
            command = build_ffsubsync_command(record.request, video_path, subtitle_path, output_path)
            record.append_log("$ " + " ".join(command))
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                record.process = process
            except Exception as exc:
                record.status = TaskStatus.FAILED
                record.error = str(exc)
                record.finished_at = _utc_now()
                record.progress_message = "启动失败"
                record.append_log(str(exc))
                return

            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                record.append_log(_decode_output_line(line))
            return_code = await process.wait()
            record.process = None
            record.finished_at = _utc_now()
            if record.cancelled:
                record.status = TaskStatus.FAILED
                record.error = "任务已取消"
                record.progress_message = "任务已取消"
                record.append_log(record.error)
            elif return_code == 0 and output_path.exists():
                record.status = TaskStatus.SUCCEEDED
                record.progress = 100
                record.progress_message = "同步完成"
            else:
                record.status = TaskStatus.FAILED
                record.progress = min(record.progress, 99)
                record.progress_message = "同步失败"
                if record.error is None:
                    record.error = f"ffsubsync exited with code {return_code}"
                    record.append_log(record.error)
