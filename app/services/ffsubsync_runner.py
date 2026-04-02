from __future__ import annotations

from pathlib import Path

from app.models import CreateTaskRequest
from app.services.sync_runner import build_sync_command


def build_ffsubsync_command(
    request: CreateTaskRequest,
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> list[str]:
    return build_sync_command(request, video_path, subtitle_path, output_path).command
