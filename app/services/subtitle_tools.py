from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import pysubs2

from app.config import Settings
from app.services.files import SUBTITLE_EXTENSIONS, relative_media_path, resolve_media_path


def ensure_supported_subtitle_name(filename: str | None) -> str:
    if not filename:
        raise ValueError("缺少字幕文件名")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUBTITLE_EXTENSIONS:
        raise ValueError("仅支持上传常见字幕文件格式")
    return filename


def build_shifted_filename(filename: str) -> str:
    path = Path(filename)
    return f"{path.stem}.shifted{path.suffix}"


def choose_shifted_output_path(directory: Path, filename: str) -> Path:
    path = Path(filename)
    base_name = f"{path.stem}.shifted"
    candidate = directory / f"{base_name}{path.suffix}"
    if not candidate.exists():
        return candidate

    counter = 1
    candidate = directory / f"{base_name}{counter}{path.suffix}"
    while candidate.exists():
        counter += 1
        candidate = directory / f"{base_name}{counter}{path.suffix}"
    return candidate


def resolve_shift_save_path(
    settings: Settings,
    source_filename: str,
    subtitle_media_path: str | None = None,
    save_dir: str | None = None,
) -> Path:
    if subtitle_media_path:
        source_path = resolve_media_path(settings, subtitle_media_path)
        target_dir = source_path.parent
    else:
        target_dir = resolve_media_path(settings, save_dir or "")

    if not target_dir.exists() or not target_dir.is_dir():
        raise FileNotFoundError("保存目录不存在")
    return choose_shifted_output_path(target_dir, source_filename)


def save_shifted_subtitle(settings: Settings, output_path: Path, content: bytes) -> str:
    output_path.write_bytes(content)
    return relative_media_path(settings, output_path)


def shift_subtitle_content(filename: str, content: bytes, offset_seconds: float, work_root: Path) -> tuple[str, bytes]:
    ensure_supported_subtitle_name(filename)
    suffix = Path(filename).suffix
    work_root.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile(delete=False, suffix=suffix, dir=work_root) as source_file:
        source_file.write(content)
        source_path = Path(source_file.name)

    output_path = source_path.with_name(f"{source_path.stem}.shifted{suffix}")
    try:
        subs = pysubs2.load(str(source_path))
        subs.shift(s=offset_seconds)
        subs.save(str(output_path))
        return build_shifted_filename(filename), output_path.read_bytes()
    finally:
        source_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


def shift_subtitle_bytes(filename: str, content: bytes, offset_seconds: float, work_root: Path) -> tuple[str, bytes]:
    return shift_subtitle_content(filename, content, offset_seconds, work_root)


def shift_subtitle_file(path: Path, offset_seconds: float, work_root: Path) -> tuple[str, bytes]:
    return shift_subtitle_content(path.name, path.read_bytes(), offset_seconds, work_root)
