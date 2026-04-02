from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pysubs2


EXTRACTABLE_SUBTITLE_CODECS = {
    "subrip": "srt",
    "ass": "ass",
    "ssa": "ssa",
    "webvtt": "vtt",
    "mov_text": "srt",
}


@dataclass(frozen=True)
class ExtractedSubtitle:
    path: Path
    stream_index: str
    codec_name: str


def _decode_process_output(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "cp936", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _subtitle_event_count(path: Path) -> int:
    try:
        return len(pysubs2.load(str(path)))
    except Exception:
        return 0


def _pick_best_extracted_subtitle(extracted_paths: list[Path], subtitle_path: Path) -> Path | None:
    target_count = _subtitle_event_count(subtitle_path)
    ranked = []
    for candidate in extracted_paths:
        candidate_count = _subtitle_event_count(candidate)
        ranked.append((abs(candidate_count - target_count), -candidate_count, candidate.name.lower(), candidate))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[:3])
    return ranked[0][3]


def extract_best_embedded_subtitle(
    video_path: Path,
    subtitle_path: Path,
    output_root: Path,
) -> ExtractedSubtitle | None:
    ffprobe_command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_name:stream_tags=language,title",
        "-of",
        "csv=p=0",
        str(video_path),
    ]
    probe = subprocess.run(ffprobe_command, capture_output=True, check=False)
    if probe.returncode != 0:
        return None

    compatible_streams: list[tuple[str, str, str]] = []
    probe_stdout = _decode_process_output(probe.stdout)
    for line in probe_stdout.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        stream_index, codec_name = parts[0], parts[1]
        language = parts[2] if len(parts) > 2 else ""
        if codec_name in EXTRACTABLE_SUBTITLE_CODECS:
            compatible_streams.append((stream_index, codec_name, language))

    if not compatible_streams:
        return None

    extraction_dir = output_root / f"embedded_subtitles_{video_path.stem}"
    extraction_dir.mkdir(parents=True, exist_ok=True)

    extracted_files: list[tuple[Path, str, str]] = []
    for position, (stream_index, codec_name, language) in enumerate(compatible_streams, start=1):
        suffix = EXTRACTABLE_SUBTITLE_CODECS[codec_name]
        language_suffix = f"_{language}" if language else ""
        output_path = extraction_dir / f"stream_{position}{language_suffix}.{suffix}"
        ffmpeg_command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-map",
            f"0:{stream_index}",
            "-c:s",
            codec_name,
            str(output_path),
        ]
        run = subprocess.run(ffmpeg_command, capture_output=True, check=False)
        if run.returncode == 0 and output_path.exists():
            extracted_files.append((output_path, stream_index, codec_name))

    best_path = _pick_best_extracted_subtitle([item[0] for item in extracted_files], subtitle_path)
    if best_path is None:
        return None

    for candidate_path, stream_index, codec_name in extracted_files:
        if candidate_path == best_path:
            return ExtractedSubtitle(path=candidate_path, stream_index=stream_index, codec_name=codec_name)
    return None
