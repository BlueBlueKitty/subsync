from __future__ import annotations

import importlib.resources
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from app.models import CreateTaskRequest, SyncTool


def _normalize(path: Path) -> str:
    return path.as_posix()


def _base_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _resources_dir() -> Path:
    return _base_dir() / "resources" / "engines"


@dataclass(frozen=True)
class SyncCommand:
    command: list[str]
    display_command: list[str]
    env: dict[str, str] | None = None


def _build_ffsubsync_command(
    request: CreateTaskRequest,
    reference_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> SyncCommand:
    command = [
        "ffsubsync",
        _normalize(reference_path),
        "-i",
        _normalize(subtitle_path),
        "-o",
        _normalize(output_path),
    ]
    if request.encoding:
        command.extend(["--encoding", request.encoding])
    if request.max_offset_seconds is not None:
        command.extend(["--max-offset-seconds", str(request.max_offset_seconds)])
    if request.ffsubsync_vad != "default":
        command.extend(["--vad", request.ffsubsync_vad])
    if request.no_fix_framerate:
        command.append("--no-fix-framerate")
    if request.gss:
        command.append("--gss")
    return SyncCommand(command=command, display_command=command)


def _resolve_alass_executable() -> str:
    configured = os.getenv("ALASS_CLI_PATH", "").strip()
    if configured:
        return configured

    system_name = platform.system()
    resources_root = _resources_dir() / "alass"
    if system_name == "Windows":
        bundled = resources_root / "windows" / "alass-cli.exe"
        if bundled.exists():
            return str(bundled)
    elif system_name == "Linux":
        bundled = resources_root / "linux" / "alass-cli"
        if bundled.exists():
            return str(bundled)

    for candidate in ("alass-cli", "alass-cli.exe", "alass"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "alass-cli"


def _build_alass_command(
    request: CreateTaskRequest,
    reference_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> SyncCommand:
    executable = _resolve_alass_executable()
    command = [
        executable,
        _normalize(reference_path),
        _normalize(subtitle_path),
        _normalize(output_path),
    ]
    if request.alass_disable_fps_guessing:
        command.append("--disable-fps-guessing")
    if request.alass_disable_speed_optimization:
        command.append("--speed-optimization=0")
    if request.alass_split_penalty < 0:
        command.append("--no-split")
    else:
        command.extend(["--split-penalty", str(request.alass_split_penalty)])
    return SyncCommand(command=command, display_command=command)


def _resolve_autosubsync_model() -> Path | None:
    configured = os.getenv("AUTOSUBSYNC_MODEL_FILE", "").strip()
    if configured:
        candidate = Path(configured)
        if candidate.exists():
            return candidate

    bundled = _resources_dir() / "autosubsync" / "trained-model.bin"
    if bundled.exists():
        return bundled

    resource_packages = ["autosubsync.resources.autosubsync", "autosubsync.resources"]
    for package_name in resource_packages:
        try:
            resource = importlib.resources.files(package_name).joinpath("trained-model.bin")
        except (ModuleNotFoundError, FileNotFoundError, AttributeError):
            continue
        with importlib.resources.as_file(resource) as resolved_path:
            if resolved_path.exists():
                return resolved_path
    return None


def _build_autosubsync_command(
    request: CreateTaskRequest,
    reference_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> SyncCommand:
    command = [
        sys.executable,
        "-m",
        "autosubsync.main",
        _normalize(reference_path),
        _normalize(subtitle_path),
        _normalize(output_path),
        "--max_shift_secs",
        str(request.autosubsync_max_shift_secs),
        "--parallelism",
        str(request.autosubsync_parallelism),
    ]
    model_path = _resolve_autosubsync_model()
    if model_path is not None:
        command.extend(["--model_file", _normalize(model_path)])
    return SyncCommand(command=command, display_command=command, env=os.environ.copy())


def build_sync_command(
    request: CreateTaskRequest,
    reference_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> SyncCommand:
    if request.sync_tool == SyncTool.ALASS:
        return _build_alass_command(request, reference_path, subtitle_path, output_path)
    if request.sync_tool == SyncTool.AUTOSUBSYNC:
        return _build_autosubsync_command(request, reference_path, subtitle_path, output_path)
    return _build_ffsubsync_command(request, reference_path, subtitle_path, output_path)
