from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.config import Settings

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".ts"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".sub", ".vtt"}
SortBy = Literal["name", "modified", "size"]
SortOrder = Literal["asc", "desc"]


@dataclass(frozen=True)
class FileEntry:
    name: str
    path: str
    is_dir: bool
    modified_at: float
    size: int


def _normalize_relative_path(relative_dir: str | None) -> str:
    return (relative_dir or "").replace("\\", "/").strip("/")


def _ensure_under_root(root: Path, target: Path) -> Path:
    resolved_target = target.resolve()
    resolved_root = root.resolve()
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise ValueError("Path must stay within MEDIA_ROOT")
    return resolved_target


def resolve_media_path(settings: Settings, relative_path: str) -> Path:
    relative = relative_path.replace("\\", "/").lstrip("/")
    candidate = settings.media_root / relative
    return _ensure_under_root(settings.media_root, candidate)


def relative_media_path(settings: Settings, path: Path) -> str:
    return path.resolve().relative_to(settings.media_root.resolve()).as_posix()


def _build_entry(settings: Settings, child: Path) -> FileEntry:
    stat = child.stat()
    return FileEntry(
        name=child.name,
        path=relative_media_path(settings, child),
        is_dir=child.is_dir(),
        modified_at=stat.st_mtime,
        size=0 if child.is_dir() else stat.st_size,
    )


def _sort_entries(entries: list[FileEntry], sort_by: SortBy, order: SortOrder) -> list[FileEntry]:
    reverse = order == "desc"
    if sort_by == "modified":
        key = lambda item: (item.modified_at, item.name.lower())
    elif sort_by == "size":
        key = lambda item: (item.size, item.name.lower())
    else:
        key = lambda item: item.name.lower()
    return sorted(entries, key=key, reverse=reverse)


def _breadcrumbs(settings: Settings, directory: Path) -> list[dict[str, str]]:
    media_root = settings.media_root.resolve()
    if directory == media_root:
        return [{"name": "/", "path": ""}]

    crumbs = [{"name": "/", "path": ""}]
    current = media_root
    for part in directory.relative_to(media_root).parts:
        current = current / part
        crumbs.append({"name": part, "path": relative_media_path(settings, current)})
    return crumbs


def list_media_entries(
    settings: Settings,
    kind: str,
    relative_dir: str | None,
    sort_by: SortBy = "name",
    order: SortOrder = "asc",
    search: str = "",
) -> dict[str, object]:
    directory = resolve_media_path(settings, _normalize_relative_path(relative_dir))
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError("Directory does not exist")

    allowed = VIDEO_EXTENSIONS if kind == "video" else SUBTITLE_EXTENSIONS
    search_term = search.strip().lower()
    directories: list[FileEntry] = []
    files: list[FileEntry] = []
    for child in directory.iterdir():
        entry = _build_entry(settings, child)
        if search_term and search_term not in child.name.lower():
            continue
        if child.is_dir():
            directories.append(entry)
        elif child.suffix.lower() in allowed:
            files.append(entry)

    directories = _sort_entries(directories, sort_by, order)
    files = _sort_entries(files, sort_by, order)

    return {
        "cwd": relative_media_path(settings, directory) if directory != settings.media_root.resolve() else "",
        "breadcrumbs": _breadcrumbs(settings, directory),
        "sort_by": sort_by,
        "order": order,
        "search": search,
        "directories": [entry.__dict__ for entry in directories],
        "files": [entry.__dict__ for entry in files],
    }


def validate_media_file(settings: Settings, relative_path: str, kind: str) -> Path:
    path = resolve_media_path(settings, relative_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{relative_path} does not exist")
    allowed = VIDEO_EXTENSIONS if kind == "video" else SUBTITLE_EXTENSIONS
    if path.suffix.lower() not in allowed:
        raise ValueError(f"Unsupported {kind} file type")
    return path


def choose_output_path(video_path: Path, subtitle_suffix: str, output_name: str | None) -> Path:
    output_dir = video_path.parent
    if output_name:
        if "/" in output_name or "\\" in output_name:
            raise ValueError("output_name must be a filename only")
        candidate = output_dir / output_name
    else:
        candidate = output_dir / f"{video_path.stem}{subtitle_suffix}"
        if candidate.exists():
            counter = 2
            candidate = output_dir / f"{video_path.stem}.{counter}{subtitle_suffix}"
            while candidate.exists():
                counter += 1
                candidate = output_dir / f"{video_path.stem}.{counter}{subtitle_suffix}"
    return candidate


def build_output_path(
    settings: Settings,
    video_relative_path: str,
    subtitle_relative_path: str,
    output_name: str | None,
) -> Path:
    video_path = validate_media_file(settings, video_relative_path, "video")
    subtitle_path = validate_media_file(settings, subtitle_relative_path, "subtitle")
    output_path = choose_output_path(video_path, subtitle_path.suffix, output_name)
    return _ensure_under_root(settings.media_root, output_path)


def find_matching_subtitle(settings: Settings, video_relative_path: str) -> dict[str, str] | None:
    video_path = validate_media_file(settings, video_relative_path, "video")
    candidates = [
        item for item in video_path.parent.iterdir() if item.is_file() and item.suffix.lower() in SUBTITLE_EXTENSIONS
    ]
    if not candidates:
        return None

    video_stem = video_path.stem.lower()

    def score(candidate: Path) -> tuple[int, int, str]:
        subtitle_stem = candidate.stem.lower()
        exact = int(subtitle_stem == video_stem)
        prefix = int(subtitle_stem.startswith(video_stem))
        return (-exact, -prefix, candidate.name.lower())

    best_match = sorted(candidates, key=score)[0]
    best_stem = best_match.stem.lower()
    if best_stem != video_stem and not best_stem.startswith(video_stem):
        return None
    return {
        "name": best_match.name,
        "path": relative_media_path(settings, best_match),
        "directory": relative_media_path(settings, best_match.parent) if best_match.parent != settings.media_root.resolve() else "",
    }
