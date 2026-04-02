from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.config import Settings
from app.models import SyncTool

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


DERIVED_SUBTITLE_MARKERS = (".ffsubsync.", ".alass.", ".autosubsync.", ".shifted.")


def build_engine_output_name(subtitle_name: str, sync_tool: SyncTool) -> str:
    path = Path(subtitle_name)
    return f"{path.stem}.{sync_tool.value}{path.suffix}"


def is_derived_subtitle(path: Path) -> bool:
    lowered = path.name.lower()
    return any(marker in lowered for marker in DERIVED_SUBTITLE_MARKERS)


def choose_output_path(
    output_dir: Path,
    subtitle_name: str,
    sync_tool: SyncTool,
    output_name: str | None = None,
) -> Path:
    if output_name:
        if "/" in output_name or "\\" in output_name:
            raise ValueError("output_name must be a filename only")
        return output_dir / output_name
    return output_dir / build_engine_output_name(subtitle_name, sync_tool)


def build_output_path(
    settings: Settings,
    video_relative_path: str,
    subtitle_relative_path: str,
    sync_tool: SyncTool,
    output_name: str | None = None,
) -> Path:
    video_path = validate_media_file(settings, video_relative_path, "video")
    subtitle_path = validate_media_file(settings, subtitle_relative_path, "subtitle")
    output_path = choose_output_path(video_path.parent, subtitle_path.name, sync_tool, output_name)
    return _ensure_under_root(settings.media_root, output_path)


def find_matching_subtitle(settings: Settings, video_relative_path: str) -> dict[str, str] | None:
    video_path = validate_media_file(settings, video_relative_path, "video")
    candidates = [
        item
        for item in video_path.parent.iterdir()
        if item.is_file() and item.suffix.lower() in SUBTITLE_EXTENSIONS and not is_derived_subtitle(item)
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
        video_count = len(
            [item for item in video_path.parent.iterdir() if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS]
        )
        if len(candidates) != 1 or video_count != 1:
            return None
    return {
        "name": best_match.name,
        "path": relative_media_path(settings, best_match),
        "directory": relative_media_path(settings, best_match.parent) if best_match.parent != settings.media_root.resolve() else "",
    }


def find_subtitle_directory(settings: Settings, video_relative_path: str) -> str | None:
    video_path = validate_media_file(settings, video_relative_path, "video")
    subtitles = [
        item
        for item in video_path.parent.iterdir()
        if item.is_file() and item.suffix.lower() in SUBTITLE_EXTENSIONS and not is_derived_subtitle(item)
    ]
    if not subtitles:
        return None
    if video_path.parent == settings.media_root.resolve():
        return ""
    return relative_media_path(settings, video_path.parent)


def find_matching_video(settings: Settings, subtitle_relative_path: str) -> dict[str, str] | None:
    subtitle_path = validate_media_file(settings, subtitle_relative_path, "subtitle")
    candidates = [
        item
        for item in subtitle_path.parent.iterdir()
        if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
    ]
    if not candidates:
        return None

    subtitle_stem = subtitle_path.stem.lower()

    def score(candidate: Path) -> tuple[int, int, int, str]:
        video_stem = candidate.stem.lower()
        exact = int(video_stem == subtitle_stem)
        video_prefix = int(subtitle_stem.startswith(video_stem))
        subtitle_prefix = int(video_stem.startswith(subtitle_stem))
        return (-exact, -video_prefix, -subtitle_prefix, candidate.name.lower())

    best_match = sorted(candidates, key=score)[0]
    best_stem = best_match.stem.lower()
    if best_stem != subtitle_stem and not subtitle_stem.startswith(best_stem) and not best_stem.startswith(subtitle_stem):
        if len(candidates) != 1:
            return None
    return {
        "name": best_match.name,
        "path": relative_media_path(settings, best_match),
        "directory": relative_media_path(settings, best_match.parent) if best_match.parent != settings.media_root.resolve() else "",
    }


def discover_scan_candidates(
    settings: Settings,
    include_dirs: list[str],
    exclude_dirs: list[str],
    recursive: bool = True,
) -> list[dict[str, str]]:
    normalized_includes = include_dirs or [""]
    roots = [resolve_media_path(settings, _normalize_relative_path(path)) for path in normalized_includes]
    excluded = {
        resolve_media_path(settings, _normalize_relative_path(path)).resolve()
        for path in exclude_dirs
        if path is not None
    }

    candidates: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    def should_exclude(path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == excluded_path or excluded_path in resolved.parents for excluded_path in excluded)

    for root_dir in roots:
        if not root_dir.exists() or not root_dir.is_dir() or should_exclude(root_dir):
            continue
        directories = [root_dir]
        if recursive:
            directories.extend([path for path in root_dir.rglob("*") if path.is_dir() and not should_exclude(path)])

        for directory in directories:
            if should_exclude(directory):
                continue
            subtitles = sorted(
                [
                    item
                    for item in directory.iterdir()
                    if item.is_file() and item.suffix.lower() in SUBTITLE_EXTENSIONS and not is_derived_subtitle(item)
                ],
                key=lambda item: item.name.lower(),
            )
            for subtitle in subtitles:
                subtitle_rel = relative_media_path(settings, subtitle)
                if subtitle_rel in seen_paths:
                    continue
                seen_paths.add(subtitle_rel)
                video = find_matching_video(settings, subtitle_rel)
                if video is None:
                    continue
                candidates.append(
                    {
                        "subtitle_path": subtitle_rel,
                        "subtitle_name": subtitle.name,
                        "video_path": video["path"],
                        "video_name": video["name"],
                    }
                )

    candidates.sort(key=lambda item: item["subtitle_path"].lower())
    return candidates


def discover_batch_pairs(settings: Settings, relative_dir: str, recursive: bool = True) -> dict[str, object]:
    root_dir = resolve_media_path(settings, _normalize_relative_path(relative_dir))
    if not root_dir.exists() or not root_dir.is_dir():
        raise FileNotFoundError("Directory does not exist")

    matched_pairs: list[dict[str, str]] = []
    unmatched_videos: list[str] = []
    directories = [root_dir]
    if recursive:
        directories.extend([path for path in root_dir.rglob("*") if path.is_dir()])

    for directory in directories:
        videos = sorted(
            [item for item in directory.iterdir() if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS],
            key=lambda item: item.name.lower(),
        )
        subtitles = sorted(
            [
                item
                for item in directory.iterdir()
                if item.is_file() and item.suffix.lower() in SUBTITLE_EXTENSIONS and not is_derived_subtitle(item)
            ],
            key=lambda item: item.name.lower(),
        )
        used_subtitles: set[str] = set()

        for video in videos:
            video_rel = relative_media_path(settings, video)
            match = find_matching_subtitle(settings, video_rel)
            if match is None and len(videos) == 1 and len(subtitles) == 1:
                only_subtitle = subtitles[0]
                match = {
                    "name": only_subtitle.name,
                    "path": relative_media_path(settings, only_subtitle),
                }
            if match is None or match["path"] in used_subtitles:
                unmatched_videos.append(video_rel)
                continue
            used_subtitles.add(match["path"])
            matched_pairs.append(
                {
                    "video_path": video_rel,
                    "subtitle_path": match["path"],
                    "video_name": video.name,
                    "subtitle_name": match["name"],
                }
            )

    matched_pairs.sort(key=lambda item: item["video_path"].lower())
    unmatched_videos.sort(key=str.lower)
    return {
        "directory": relative_media_path(settings, root_dir) if root_dir != settings.media_root.resolve() else "",
        "recursive": recursive,
        "pairs": matched_pairs,
        "matched_count": len(matched_pairs),
        "unmatched_videos": unmatched_videos,
    }
