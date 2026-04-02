from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pysubs2

from app.models import CreateTaskRequest, TaskStatus
from app.services.ffsubsync_runner import build_ffsubsync_command
from app.services.files import build_output_path, find_matching_subtitle, resolve_media_path
from app.services.subtitle_tools import (
    build_shifted_filename,
    choose_shifted_output_path,
    resolve_shift_save_path,
    save_shifted_subtitle,
    shift_subtitle_bytes,
    shift_subtitle_file,
)
from app.services.tasks import TaskManager


def login(client) -> None:
    response = client.post("/login", data={"password": "secret"}, follow_redirects=False)
    assert response.status_code == 303


def test_requires_login_redirect(client) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_and_access_home(client) -> None:
    login(client)
    response = client.get("/")
    assert response.status_code == 200
    assert "ffsubsync Web" in response.text


def test_list_files_and_filter_by_kind(client, settings) -> None:
    videos = settings.media_root / "shows"
    videos.mkdir()
    (videos / "episode.mkv").write_text("video")
    (videos / "episode.srt").write_text("subtitle")
    login(client)

    response = client.get("/api/files", params={"kind": "video", "dir": "shows"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["cwd"] == "shows"
    assert payload["breadcrumbs"][-1]["path"] == "shows"
    assert [item["name"] for item in payload["files"]] == ["episode.mkv"]


def test_rejects_path_outside_media_root(settings) -> None:
    try:
        resolve_media_path(settings, "../outside.srt")
    except ValueError as exc:
        assert "MEDIA_ROOT" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_output_name_generation(settings) -> None:
    video_dir = settings.media_root / "subs"
    video_dir.mkdir()
    video = video_dir / "movie.mkv"
    video.write_text("v")
    subtitle = video_dir / "movie.zh.srt"
    subtitle.write_text("1")
    output = build_output_path(settings, "subs/movie.mkv", "subs/movie.zh.srt", None)
    assert output.name == "movie.srt"


def test_build_ffsubsync_command() -> None:
    payload = CreateTaskRequest(
        video_path="video.mkv",
        subtitle_path="movie.srt",
        output_name="movie.synced.srt",
        encoding="utf-8",
        max_offset_seconds=120,
        no_fix_framerate=True,
        gss=True,
    )
    command = build_ffsubsync_command(
        payload,
        Path("/media/video.mkv"),
        Path("/media/movie.srt"),
        Path("/media/movie.synced.srt"),
    )
    assert command == [
        "ffsubsync",
        "/media/video.mkv",
        "-i",
        "/media/movie.srt",
        "-o",
        "/media/movie.synced.srt",
        "--encoding",
        "utf-8",
        "--max-offset-seconds",
        "120",
        "--no-fix-framerate",
        "--gss",
    ]


def test_task_manager_state_flow(tmp_path: Path) -> None:
    async def runner() -> None:
        manager = TaskManager(max_concurrent_tasks=1)
        video = tmp_path / "video.mkv"
        subtitle = tmp_path / "subtitle.srt"
        output = tmp_path / "subtitle.synced.srt"
        video.write_text("video")
        subtitle.write_text("subtitle")
        output.write_text("result")

        payload = CreateTaskRequest(video_path="video.mkv", subtitle_path="subtitle.srt")

        async def fake_exec(*args, **kwargs):
            class FakeStdout:
                def __init__(self) -> None:
                    self._lines = [b"working\n", b""]

                async def readline(self):
                    return self._lines.pop(0)

            class FakeProcess:
                def __init__(self) -> None:
                    self.stdout = FakeStdout()

                async def wait(self):
                    return 0

            return FakeProcess()

        original = asyncio.create_subprocess_exec
        asyncio.create_subprocess_exec = fake_exec
        try:
            task = await manager.create_task(payload, video, subtitle, output, "media")
            assert task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}
            await asyncio.sleep(0.05)
            saved = await manager.get_task(task.task_id)
            assert saved.status == TaskStatus.SUCCEEDED
            assert "working" in saved.log_text()
        finally:
            asyncio.create_subprocess_exec = original

    asyncio.run(runner())


def test_create_task_and_poll_log(client, settings, monkeypatch) -> None:
    video = settings.media_root / "movie.mkv"
    subtitle = settings.media_root / "movie.srt"
    video.write_text("video")
    subtitle.write_text("subtitle")

    async def fake_exec(*args, **kwargs):
        output = Path(args[5])
        output.write_text("done")

        class FakeStdout:
            def __init__(self) -> None:
                self._lines = [b"line one\n", b""]

            async def readline(self):
                return self._lines.pop(0)

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout()

            async def wait(self):
                return 0

        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    login(client)

    response = client.post(
        "/api/tasks",
        data={"video_path": "movie.mkv", "subtitle_path": "movie.srt", "output_name": ""},
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    for _ in range(20):
        task_response = client.get(f"/api/tasks/{task_id}")
        if task_response.json()["status"] == "succeeded":
            break
        time.sleep(0.02)
    task_response = client.get(f"/api/tasks/{task_id}")

    log_response = client.get(f"/api/tasks/{task_id}/log")
    assert log_response.status_code == 200
    assert "line one" in log_response.json()["log"]
    assert task_response.json()["progress"] == 100


def test_subtitle_tools_page_requires_login(client) -> None:
    response = client.get("/subtitle-tools", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_shift_subtitle_bytes(settings) -> None:
    subtitle_content = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"
    filename, shifted = shift_subtitle_bytes("demo.srt", subtitle_content, 2.5, settings.work_root)
    assert filename == build_shifted_filename("demo.srt")

    output_path = settings.work_root / filename
    output_path.write_bytes(shifted)
    subs = pysubs2.load(str(output_path))
    assert subs[0].start == 3500
    assert subs[0].end == 4500


def test_shift_subtitle_api_returns_download(client, settings) -> None:
    login(client)
    response = client.post(
        "/api/subtitles/shift",
        files={"subtitle_file": ("demo.srt", b"1\n00:00:01,000 --> 00:00:02,000\nHello\n", "application/x-subrip")},
        data={"offset_seconds": "1.5"},
    )
    assert response.status_code == 200
    assert 'attachment; filename="demo.shifted.srt"' == response.headers["content-disposition"]

    output_path = settings.work_root / "demo.shifted.srt"
    output_path.write_bytes(response.content)
    subs = pysubs2.load(str(output_path))
    assert subs[0].start == 2500
    assert subs[0].end == 3500


def test_shift_subtitle_file(settings) -> None:
    subtitle = settings.media_root / "chosen.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    filename, shifted = shift_subtitle_file(subtitle, 1.0, settings.work_root)
    assert filename == "chosen.shifted.srt"
    output_path = settings.work_root / filename
    output_path.write_bytes(shifted)
    subs = pysubs2.load(str(output_path))
    assert subs[0].start == 2000


def test_shift_subtitle_api_supports_media_selection(client, settings) -> None:
    subtitle = settings.media_root / "picked.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    login(client)
    response = client.post(
        "/api/subtitles/shift",
        data={"subtitle_mode": "media", "subtitle_path": "picked.srt", "offset_seconds": "2.0"},
    )
    assert response.status_code == 200
    assert 'attachment; filename="picked.shifted.srt"' == response.headers["content-disposition"]


def test_choose_shifted_output_path_adds_numeric_suffix(tmp_path: Path) -> None:
    directory = tmp_path
    (directory / "demo.shifted.srt").write_text("1")
    (directory / "demo.shifted1.srt").write_text("1")
    output = choose_shifted_output_path(directory, "demo.srt")
    assert output.name == "demo.shifted2.srt"


def test_shift_subtitle_api_can_save_to_media(client, settings) -> None:
    subtitle = settings.media_root / "saved.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    login(client)
    response = client.post(
        "/api/subtitles/shift",
        data={
            "subtitle_mode": "media",
            "subtitle_path": "saved.srt",
            "save_mode": "save",
            "offset_seconds": "2.0",
        },
    )
    assert response.status_code == 200
    assert response.json()["saved_path"] == "saved.shifted.srt"
    assert (settings.media_root / "saved.shifted.srt").exists()


def test_shift_subtitle_api_can_save_and_download_uploaded_subtitle(client, settings) -> None:
    (settings.media_root / "folder").mkdir()
    login(client)
    response = client.post(
        "/api/subtitles/shift",
        files={"subtitle_file": ("upload.srt", b"1\n00:00:01,000 --> 00:00:02,000\nHello\n", "application/x-subrip")},
        data={
            "subtitle_mode": "upload",
            "save_mode": "save_and_download",
            "save_dir": "folder",
            "offset_seconds": "1.0",
        },
    )
    assert response.status_code == 200
    assert response.headers["x-saved-path"] == "folder/upload.shifted.srt"
    assert (settings.media_root / "folder" / "upload.shifted.srt").exists()


def test_find_matching_subtitle_prefers_same_stem(settings) -> None:
    media_dir = settings.media_root / "movies"
    media_dir.mkdir()
    (media_dir / "film.mkv").write_text("video")
    (media_dir / "film.zh.srt").write_text("subtitle")
    (media_dir / "other.srt").write_text("subtitle")

    match = find_matching_subtitle(settings, "movies/film.mkv")
    assert match is not None
    assert match["path"] == "movies/film.zh.srt"


def test_match_subtitle_api_returns_none_when_not_found(client, settings) -> None:
    media_dir = settings.media_root / "series"
    media_dir.mkdir()
    (media_dir / "ep01.mkv").write_text("video")
    (media_dir / "random.srt").write_text("subtitle")
    login(client)

    response = client.get("/api/subtitles/match", params={"video_path": "series/ep01.mkv"})
    assert response.status_code == 200
    assert response.json()["match"] is None


def test_upload_task_returns_downloadable_output(client, settings, monkeypatch) -> None:
    video = settings.media_root / "clip.mp4"
    video.write_text("video")

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[5])
        output_path.write_text("done")

        class FakeStdout:
            def __init__(self) -> None:
                self._lines = ["中文日志\n".encode("gb18030"), b""]

            async def readline(self):
                return self._lines.pop(0)

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout()

            async def wait(self):
                return 0

        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    login(client)
    response = client.post(
        "/api/tasks",
        files={
            "subtitle_file": ("clip.srt", b"1\n00:00:01,000 --> 00:00:02,000\nHello\n", "application/x-subrip"),
        },
        data={"video_path": "clip.mp4", "subtitle_mode": "upload", "output_name": ""},
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    time.sleep(0.05)
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["can_download_output"] is True
    assert task["status"] == "succeeded"
    assert task["output_name"].startswith("clip")
    log = client.get(f"/api/tasks/{task_id}/log").json()
    assert "中文日志" in log["log"]
    download = client.get(f"/api/tasks/{task_id}/download")
    assert download.status_code == 200
