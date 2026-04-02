from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.models import CreateTaskRequest, SyncTool, TaskStatus, TaskSummary
from app.services.embedded_subtitles import extract_best_embedded_subtitle
from app.services.sync_runner import build_sync_command

MAX_TASK_HISTORY = 100


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
    sync_tool: SyncTool
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
        if self.sync_tool == SyncTool.ALASS:
            self._update_alass_progress(text)
        elif self.sync_tool == SyncTool.AUTOSUBSYNC:
            self._update_autosubsync_progress(text)
        else:
            self._update_ffsubsync_progress(text)

    def _update_ffsubsync_progress(self, text: str) -> None:
        lowered = text.lower()
        if "extracting speech segments from reference" in lowered:
            self.progress = max(self.progress, 10)
            self.progress_message = "提取视频语音片段"
        elif "extracting speech segments from subtitles" in lowered:
            self.progress = max(self.progress, 35)
            self.progress_message = "解析字幕时间轴"
        elif "computing alignments" in lowered:
            self.progress = max(self.progress, 70)
            self.progress_message = "计算时间轴对齐"
        elif "writing output to" in lowered:
            self.progress = max(self.progress, 90)
            self.progress_message = "写入输出字幕"
        elif "100%|" in text:
            self.progress = max(self.progress, 55)
            if self.progress_message == "提取视频语音片段":
                self.progress_message = "语音提取完成"

    def _update_alass_progress(self, text: str) -> None:
        lowered = text.lower()
        if "loading file" in lowered or "video file" in lowered:
            self.progress = max(self.progress, 15)
            self.progress_message = "加载参考文件"
        elif "rating segments" in lowered or "shift" in lowered:
            self.progress = max(self.progress, 60)
            self.progress_message = "计算字幕对齐"
        elif "writing" in lowered or "output" in lowered:
            self.progress = max(self.progress, 90)
            self.progress_message = "写入输出字幕"

    def _update_autosubsync_progress(self, text: str) -> None:
        lowered = text.lower()
        if "extract" in lowered and "audio" in lowered:
            self.progress = max(self.progress, 20)
            self.progress_message = "提取视频音频"
        elif "speech" in lowered or "vad" in lowered:
            self.progress = max(self.progress, 50)
            self.progress_message = "分析语音活动"
        elif "shift" in lowered or "align" in lowered or "sync" in lowered:
            self.progress = max(self.progress, 75)
            self.progress_message = "计算字幕偏移"
        elif "writing" in lowered or "output" in lowered:
            self.progress = max(self.progress, 90)
            self.progress_message = "写入输出字幕"

    def log_text(self) -> str:
        return "\n".join(self.log_lines)

    def to_summary(self) -> TaskSummary:
        return TaskSummary(
            task_id=self.task_id,
            sync_tool=self.sync_tool,
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
    def __init__(self, max_concurrent_tasks: int, temp_root: Path | None = None) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._task_order: list[str] = []
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._max_task_history = MAX_TASK_HISTORY
        self._temp_root = temp_root or (Path.cwd() / ".subsync-temp")

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
            sync_tool=request.sync_tool,
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
            self._trim_task_history_locked()
        if source_type == "scheduled":
            record.append_log("自动扫描已创建同步任务")
        asyncio.create_task(self._run_task(record, video_path, subtitle_path, output_path))
        return record

    async def create_tasks_batch(
        self,
        items: list[tuple[CreateTaskRequest, Path, Path, Path, str]],
    ) -> list[TaskRecord]:
        created: list[TaskRecord] = []
        for request, video_path, subtitle_path, output_path, source_type in items:
            created.append(await self.create_task(request, video_path, subtitle_path, output_path, source_type))
        return created

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

    def _trim_task_history_locked(self) -> None:
        while len(self._task_order) > self._max_task_history:
            removable_task_id = next(
                (
                    task_id
                    for task_id in reversed(self._task_order)
                    if self._tasks[task_id].status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}
                ),
                None,
            )
            if removable_task_id is None:
                break
            self._task_order.remove(removable_task_id)
            self._tasks.pop(removable_task_id, None)

    async def _run_task(
        self,
        record: TaskRecord,
        video_path: Path,
        subtitle_path: Path,
        output_path: Path,
    ) -> None:
        async with self._semaphore:
            runtime_request = record.request.model_copy(deep=True)
            reference_path = video_path
            extraction_root = self._temp_root / "embedded_subtitles" / record.task_id
            extraction_enabled = (
                (runtime_request.sync_tool == SyncTool.FFSUBSYNC and runtime_request.ffsubsync_use_embedded_subtitles)
                or
                (runtime_request.sync_tool == SyncTool.ALASS and runtime_request.alass_use_embedded_subtitles)
                or (
                    runtime_request.sync_tool == SyncTool.AUTOSUBSYNC
                    and runtime_request.autosubsync_use_embedded_subtitles
                )
            )
            if extraction_enabled:
                extracted = extract_best_embedded_subtitle(
                    video_path,
                    subtitle_path,
                    extraction_root,
                )
                if extracted is not None:
                    if runtime_request.sync_tool == SyncTool.AUTOSUBSYNC:
                        record.append_log("autosubsync 不支持字幕参考，检测到内嵌字幕后自动回退到 ffsubsync")
                        runtime_request.sync_tool = SyncTool.FFSUBSYNC
                        record.sync_tool = SyncTool.FFSUBSYNC
                    elif runtime_request.sync_tool == SyncTool.FFSUBSYNC:
                        record.append_log(f"ffsubsync 已使用视频内嵌字幕作为参考：{extracted.path.name}")
                    else:
                        record.append_log(f"已使用视频内嵌字幕作为参考：{extracted.path.name}")
                    reference_path = extracted.path
                else:
                    record.append_log("未找到可用的内嵌字幕，将继续使用视频音频作为参考")

            try:
                record.status = TaskStatus.RUNNING
                record.started_at = _utc_now()
                record.progress = 5
                launch_tool = runtime_request.sync_tool.value
                record.progress_message = f"启动 {launch_tool}"
                sync_command = build_sync_command(runtime_request, reference_path, subtitle_path, output_path)
                record.append_log("$ " + " ".join(sync_command.display_command))
                try:
                    process = await asyncio.create_subprocess_exec(
                        *sync_command.command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        env=sync_command.env,
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
                    record.can_download_output = True
                    record.append_log(f"同步完成：{output_path.name}")
                else:
                    record.status = TaskStatus.FAILED
                    record.progress = min(record.progress, 99)
                    record.progress_message = "同步失败"
                    if record.error is None:
                        record.error = f"{record.sync_tool.value} exited with code {return_code}"
                        record.append_log(record.error)
            finally:
                shutil.rmtree(extraction_root, ignore_errors=True)
                async with self._lock:
                    self._trim_task_history_locked()
