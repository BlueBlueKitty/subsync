from __future__ import annotations

from pathlib import Path

from app.models import CreateTaskRequest


def build_ffsubsync_command(
    request: CreateTaskRequest,
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> list[str]:
    def normalize(path: Path) -> str:
        return path.as_posix()

    command = [
        "ffsubsync",
        normalize(video_path),
        "-i",
        normalize(subtitle_path),
        "-o",
        normalize(output_path),
    ]
    if request.encoding:
        command.extend(["--encoding", request.encoding])
    if request.max_offset_seconds is not None:
        command.extend(["--max-offset-seconds", str(request.max_offset_seconds)])
    if request.no_fix_framerate:
        command.append("--no-fix-framerate")
    if request.gss:
        command.append("--gss")
    return command
