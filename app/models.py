from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SyncTool(str, Enum):
    FFSUBSYNC = "ffsubsync"
    ALASS = "alass"
    AUTOSUBSYNC = "autosubsync"


class CreateTaskRequest(BaseModel):
    sync_tool: SyncTool = SyncTool.FFSUBSYNC
    video_path: str = Field(min_length=1)
    subtitle_path: str = Field(min_length=1)
    output_name: Optional[str] = None
    encoding: Optional[str] = None
    max_offset_seconds: Optional[int] = Field(default=None, ge=1)
    ffsubsync_use_embedded_subtitles: bool = True
    no_fix_framerate: bool = False
    gss: bool = False
    ffsubsync_vad: str = "default"
    alass_use_embedded_subtitles: bool = True
    alass_disable_fps_guessing: bool = False
    alass_disable_speed_optimization: bool = False
    alass_split_penalty: int = Field(default=7, ge=-1, le=1000)
    autosubsync_use_embedded_subtitles: bool = True
    autosubsync_max_shift_secs: int = Field(default=20, ge=1, le=120)
    autosubsync_parallelism: int = Field(default=3, ge=1, le=16)


class TaskSummary(BaseModel):
    task_id: str
    sync_tool: SyncTool = SyncTool.FFSUBSYNC
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    video_path: str
    subtitle_path: str
    output_path: Optional[str] = None
    output_name: Optional[str] = None
    progress: int = 0
    progress_message: str = ""
    source_type: str = "media"
    can_download_output: bool = False
    error: Optional[str] = None


class TaskLogResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int
    log: str


class SchedulerEngineOptions(BaseModel):
    ffsubsync_use_embedded_subtitles: bool = True
    ffsubsync_vad: str = "default"
    no_fix_framerate: bool = False
    gss: bool = False
    alass_use_embedded_subtitles: bool = True
    alass_disable_fps_guessing: bool = False
    alass_disable_speed_optimization: bool = False
    alass_split_penalty: int = Field(default=7, ge=-1, le=1000)
    autosubsync_use_embedded_subtitles: bool = True
    autosubsync_max_shift_secs: int = Field(default=20, ge=1, le=120)
    autosubsync_parallelism: int = Field(default=3, ge=1, le=16)


class SchedulerConfig(BaseModel):
    enabled: bool = False
    run_on_startup: bool = True
    scan_time: str = Field(default="03:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    recursive: bool = True
    include_dirs: list[str] = Field(default_factory=list)
    exclude_dirs: list[str] = Field(default_factory=list)
    enabled_engines: list[SyncTool] = Field(default_factory=lambda: [SyncTool.FFSUBSYNC])
    engine_options: SchedulerEngineOptions = Field(default_factory=SchedulerEngineOptions)


class SchedulerStatus(BaseModel):
    is_running: bool = False
    last_started_at: Optional[datetime] = None
    last_finished_at: Optional[datetime] = None
    last_status: str = "idle"
    last_summary: str = "尚未执行扫描"
    last_error: Optional[str] = None


class SchedulerStateResponse(BaseModel):
    config: SchedulerConfig
    status: SchedulerStatus
