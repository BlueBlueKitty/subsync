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


class CreateTaskRequest(BaseModel):
    video_path: str = Field(min_length=1)
    subtitle_path: str = Field(min_length=1)
    output_name: Optional[str] = None
    encoding: Optional[str] = None
    max_offset_seconds: Optional[int] = Field(default=None, ge=1)
    no_fix_framerate: bool = False
    gss: bool = False


class TaskSummary(BaseModel):
    task_id: str
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
