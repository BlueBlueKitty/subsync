from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pysubs2

from app.models import CreateTaskRequest, SyncTool, TaskStatus
from app.services.ffsubsync_runner import build_ffsubsync_command
from app.services.files import (
    build_output_path,
    build_engine_output_name,
    discover_batch_pairs,
    discover_scan_candidates,
    find_matching_subtitle,
    resolve_media_path,
)
from app.services.sync_runner import build_sync_command
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
    assert "subsync" in response.text


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
    output = build_output_path(settings, "subs/movie.mkv", "subs/movie.zh.srt", SyncTool.FFSUBSYNC)
    assert output.name == "movie.zh.ffsubsync.srt"


def test_output_name_generation_avoids_overwrite(settings) -> None:
    video_dir = settings.media_root / "subs"
    video_dir.mkdir()
    (video_dir / "movie.mkv").write_text("v")
    (video_dir / "movie.zh.srt").write_text("1")
    (video_dir / "movie.zh.ffsubsync.srt").write_text("old")
    output = build_output_path(settings, "subs/movie.mkv", "subs/movie.zh.srt", SyncTool.FFSUBSYNC)
    assert output.name == "movie.zh.ffsubsync.srt"


def test_build_engine_output_name() -> None:
    assert build_engine_output_name("movie.zh.srt", SyncTool.ALASS) == "movie.zh.alass.srt"


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


def test_build_ffsubsync_command_with_vad() -> None:
    payload = CreateTaskRequest(
        sync_tool=SyncTool.FFSUBSYNC,
        video_path="video.mkv",
        subtitle_path="movie.srt",
        ffsubsync_vad="webrtc",
    )
    command = build_sync_command(
        payload,
        Path("/media/video.mkv"),
        Path("/media/movie.srt"),
        Path("/media/movie.synced.srt"),
    )
    assert command.command == [
        "ffsubsync",
        "/media/video.mkv",
        "-i",
        "/media/movie.srt",
        "-o",
        "/media/movie.synced.srt",
        "--vad",
        "webrtc",
    ]


def test_scheduler_settings_api_roundtrip_includes_ffsubsync_embedded_subtitles(client, settings) -> None:
    login(client)
    update = client.post(
        "/api/settings/scheduler",
        json={
            "enabled": True,
            "run_on_startup": True,
            "scan_time": "02:30",
            "recursive": False,
            "include_dirs": ["tv"],
            "exclude_dirs": ["tv/cache"],
            "enabled_engines": ["ffsubsync"],
            "engine_options": {
                "ffsubsync_use_embedded_subtitles": True,
                "ffsubsync_vad": "webrtc",
                "no_fix_framerate": True,
                "gss": True,
                "alass_use_embedded_subtitles": True,
                "alass_disable_fps_guessing": False,
                "alass_disable_speed_optimization": True,
                "alass_split_penalty": 12,
                "autosubsync_use_embedded_subtitles": True,
                "autosubsync_max_shift_secs": 20,
                "autosubsync_parallelism": 3,
            },
        },
    )
    assert update.status_code == 200
    updated = update.json()
    assert updated["config"]["engine_options"]["ffsubsync_use_embedded_subtitles"] is True


def test_build_alass_command_uses_bundled_executable() -> None:
    payload = CreateTaskRequest(
        sync_tool=SyncTool.ALASS,
        video_path="video.mkv",
        subtitle_path="movie.srt",
        alass_disable_fps_guessing=True,
        alass_disable_speed_optimization=True,
        alass_split_penalty=-1,
    )
    command = build_sync_command(
        payload,
        Path("/media/video.mkv"),
        Path("/media/movie.srt"),
        Path("/media/movie.synced.srt"),
    )
    assert command.command[0].replace("\\", "/").endswith("resources/engines/alass/windows/alass-cli.exe")
    assert command.command[1:] == [
        "/media/video.mkv",
        "/media/movie.srt",
        "/media/movie.synced.srt",
        "--disable-fps-guessing",
        "--speed-optimization=0",
        "--no-split",
    ]


def test_build_autosubsync_command_uses_installed_module_and_bundled_model() -> None:
    payload = CreateTaskRequest(
        sync_tool=SyncTool.AUTOSUBSYNC,
        video_path="video.mkv",
        subtitle_path="movie.srt",
        autosubsync_max_shift_secs=42,
        autosubsync_parallelism=5,
    )
    command = build_sync_command(
        payload,
        Path("/media/video.mkv"),
        Path("/media/movie.srt"),
        Path("/media/movie.synced.srt"),
    )
    assert command.command[0].replace("\\", "/").endswith("python.exe")
    assert command.command[1:3] == ["-m", "autosubsync.main"]
    assert command.command[3:] == [
        "/media/video.mkv",
        "/media/movie.srt",
        "/media/movie.synced.srt",
        "--max_shift_secs",
        "42",
        "--parallelism",
        "5",
        "--model_file",
        command.command[-1],
    ]
    assert command.env is not None
    assert command.command[-1].replace("\\", "/").endswith("resources/engines/autosubsync/trained-model.bin")


def test_task_manager_state_flow(tmp_path: Path) -> None:
    async def runner() -> None:
        manager = TaskManager(max_concurrent_tasks=1, temp_root=tmp_path / "tmp")
        video = tmp_path / "video.mkv"
        subtitle = tmp_path / "subtitle.srt"
        output = tmp_path / "subtitle.ffsubsync.srt"
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
            assert saved.sync_tool == SyncTool.FFSUBSYNC
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
    assert task_response.json()["sync_tool"] == "ffsubsync"
    assert task_response.json()["output_name"] == "movie.ffsubsync.srt"


def test_create_alass_task_records_sync_tool(client, settings, monkeypatch) -> None:
    video = settings.media_root / "movie.mkv"
    subtitle = settings.media_root / "movie.srt"
    video.write_text("video")
    subtitle.write_text("subtitle")

    async def fake_exec(*args, **kwargs):
        output = Path(args[3])
        output.write_text("done")

        class FakeStdout:
            def __init__(self) -> None:
                self._lines = [b"writing output\n", b""]

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
        data={
            "video_path": "movie.mkv",
            "subtitle_path": "movie.srt",
            "sync_tool": "alass",
            "alass_split_penalty": "-1",
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    time.sleep(0.05)
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["sync_tool"] == "alass"
    assert task["status"] == "succeeded"


def test_subtitle_tools_page_requires_login(client) -> None:
    response = client.get("/subtitle-tools", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_shift_subtitle_bytes(settings) -> None:
    subtitle_content = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"
    filename, shifted = shift_subtitle_bytes("demo.srt", subtitle_content, 2.5, settings.temp_dir)
    assert filename == build_shifted_filename("demo.srt")

    output_path = settings.temp_dir / filename
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
    assert 'filename="demo.shifted.srt"' in response.headers["content-disposition"]

    output_path = settings.temp_dir / "demo.shifted.srt"
    output_path.write_bytes(response.content)
    subs = pysubs2.load(str(output_path))
    assert subs[0].start == 2500
    assert subs[0].end == 3500


def test_shift_subtitle_file(settings) -> None:
    subtitle = settings.media_root / "chosen.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    filename, shifted = shift_subtitle_file(subtitle, 1.0, settings.temp_dir)
    assert filename == "chosen.shifted.srt"
    output_path = settings.temp_dir / filename
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
    assert 'filename="picked.shifted.srt"' in response.headers["content-disposition"]


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
    (media_dir / "other.srt").write_text("subtitle")
    login(client)

    response = client.get("/api/subtitles/match", params={"video_path": "series/ep01.mkv"})
    assert response.status_code == 200
    assert response.json()["match"] is None
    assert response.json()["directory"] == "series"


def test_match_subtitle_api_falls_back_to_single_subtitle_in_directory(client, settings) -> None:
    media_dir = settings.media_root / "movies"
    media_dir.mkdir()
    (media_dir / "看见恶魔.mkv").write_text("video")
    (media_dir / "I.Saw.The.Devil.2010.Chs.srt").write_text("subtitle")
    login(client)

    response = client.get("/api/subtitles/match", params={"video_path": "movies/看见恶魔.mkv"})
    assert response.status_code == 200
    assert response.json()["match"]["path"] == "movies/I.Saw.The.Devil.2010.Chs.srt"


def test_discover_batch_pairs(settings) -> None:
    root = settings.media_root / "batch"
    root.mkdir()
    (root / "ep01.mkv").write_text("video")
    (root / "ep01.zh.srt").write_text("subtitle")
    (root / "ep02.mkv").write_text("video")

    payload = discover_batch_pairs(settings, "batch")
    assert payload["matched_count"] == 1
    assert payload["pairs"][0]["video_path"] == "batch/ep01.mkv"
    assert payload["pairs"][0]["subtitle_path"] == "batch/ep01.zh.srt"
    assert payload["unmatched_videos"] == ["batch/ep02.mkv"]


def test_discover_batch_pairs_falls_back_to_single_video_single_subtitle_per_directory(settings) -> None:
    root = settings.media_root / "tv" / "movie-folder"
    root.mkdir(parents=True)
    (root / "看见恶魔.mkv").write_text("video")
    (root / "I.Saw.The.Devil.2010.Chs.srt").write_text("subtitle")

    payload = discover_batch_pairs(settings, "tv")
    assert payload["matched_count"] == 1
    assert payload["pairs"][0]["video_path"] == "tv/movie-folder/看见恶魔.mkv"
    assert payload["pairs"][0]["subtitle_path"] == "tv/movie-folder/I.Saw.The.Devil.2010.Chs.srt"


def test_discover_scan_candidates_skips_derived_subtitles(settings) -> None:
    root = settings.media_root / "library"
    root.mkdir()
    (root / "movie.mkv").write_text("video")
    (root / "movie.zh.srt").write_text("subtitle")
    (root / "movie.zh.ffsubsync.srt").write_text("derived")
    (root / "movie.zh.shifted.srt").write_text("manual")

    payload = discover_scan_candidates(settings, ["library"], [], recursive=True)
    assert len(payload) == 1
    assert payload[0]["subtitle_path"] == "library/movie.zh.srt"
    assert payload[0]["video_path"] == "library/movie.mkv"


def test_batch_preview_api_and_create_tasks(client, settings, monkeypatch) -> None:
    folder = settings.media_root / "season1"
    folder.mkdir()
    (folder / "s01e01.mkv").write_text("video")
    (folder / "s01e01.srt").write_text("subtitle")
    (folder / "s01e02.mkv").write_text("video")
    (folder / "s01e02.ass").write_text("subtitle")

    async def fake_exec(*args, **kwargs):
        output_index = args.index("-o") + 1 if "-o" in args else 3
        Path(args[output_index]).write_text("done")

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

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    login(client)

    preview = client.get("/api/tasks/batch-preview", params={"dir": "season1"})
    assert preview.status_code == 200
    assert preview.json()["matched_count"] == 2

    response = client.post(
        "/api/tasks/batch",
        data={
            "batch_dir": "season1",
            "sync_tool": "ffsubsync",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 2
    assert len(payload["task_ids"]) == 2

    time.sleep(0.05)
    tasks = client.get("/api/tasks").json()["tasks"]
    assert len(tasks) >= 2
    assert tasks[0]["output_name"].endswith(".ffsubsync.ass") or tasks[0]["output_name"].endswith(".ffsubsync.srt")


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
    assert task["output_name"] == "clip.ffsubsync.srt"
    log = client.get(f"/api/tasks/{task_id}/log").json()
    assert "中文日志" in log["log"]
    download = client.get(f"/api/tasks/{task_id}/download")
    assert download.status_code == 200


def test_media_task_returns_downloadable_output_with_unicode_filename(client, settings, monkeypatch) -> None:
    video = settings.media_root / "看见恶魔.mkv"
    subtitle = settings.media_root / "英文字幕.srt"
    video.write_text("video")
    subtitle.write_text("subtitle")

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[5])
        output_path.write_text("done")

        class FakeStdout:
            def __init__(self) -> None:
                self._lines = [b"done\n", b""]

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
        data={"video_path": "看见恶魔.mkv", "subtitle_path": "英文字幕.srt", "output_name": ""},
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    time.sleep(0.05)
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["can_download_output"] is True
    assert task["status"] == "succeeded"

    download = client.get(f"/api/tasks/{task_id}/download")
    assert download.status_code == 200
    assert "filename*=UTF-8''" in download.headers["content-disposition"]


def test_task_manager_keeps_only_recent_completed_tasks(tmp_path: Path) -> None:
    async def runner() -> None:
        manager = TaskManager(max_concurrent_tasks=1, temp_root=tmp_path / "tmp")
        video = tmp_path / "video.mkv"
        subtitle = tmp_path / "subtitle.srt"
        video.write_text("video")
        subtitle.write_text("subtitle")

        async def fake_exec(*args, **kwargs):
            output = Path(args[5])
            output.write_text("done")

            class FakeStdout:
                def __init__(self) -> None:
                    self._lines = [b"done\n", b""]

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
            for index in range(105):
                output = tmp_path / f"subtitle-{index}.ffsubsync.srt"
                payload = CreateTaskRequest(video_path="video.mkv", subtitle_path="subtitle.srt")
                await manager.create_task(payload, video, subtitle, output, "media")
            await asyncio.sleep(0.2)
            tasks = await manager.list_tasks()
            assert len(tasks) == 100
        finally:
            asyncio.create_subprocess_exec = original

    asyncio.run(runner())


def test_settings_directories_and_scheduler_files_exist(client, settings) -> None:
    login(client)
    assert settings.config_dir.exists()
    assert settings.uploads_dir.exists()
    assert settings.runtime_dir.exists()
    assert settings.temp_dir.exists()
    assert (settings.config_dir / "scheduler.json").exists()
    assert (settings.runtime_dir / "scheduler_status.json").exists()


def test_scheduler_settings_api_roundtrip(client, settings) -> None:
    login(client)
    response = client.get("/api/settings/scheduler")
    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["enabled"] is False

    update = client.post(
        "/api/settings/scheduler",
        json={
            "enabled": True,
            "run_on_startup": True,
            "scan_time": "02:30",
            "recursive": False,
            "include_dirs": ["tv"],
            "exclude_dirs": ["tv/cache"],
            "enabled_engines": ["ffsubsync", "alass"],
            "engine_options": {
                "ffsubsync_vad": "webrtc",
                "no_fix_framerate": True,
                "gss": True,
                "alass_use_embedded_subtitles": True,
                "alass_disable_fps_guessing": False,
                "alass_disable_speed_optimization": True,
                "alass_split_penalty": 12,
                "autosubsync_use_embedded_subtitles": True,
                "autosubsync_max_shift_secs": 20,
                "autosubsync_parallelism": 3,
            },
        },
    )
    assert update.status_code == 200
    updated = update.json()
    assert updated["config"]["enabled"] is True
    assert updated["config"]["scan_time"] == "02:30"
    assert updated["config"]["enabled_engines"] == ["ffsubsync", "alass"]

    saved = (settings.config_dir / "scheduler.json").read_text(encoding="utf-8")
    assert '"scan_time": "02:30"' in saved


def test_scheduler_run_now_creates_tasks_for_missing_outputs(client, settings, monkeypatch) -> None:
    folder = settings.media_root / "movies"
    folder.mkdir()
    (folder / "movie.mkv").write_text("video")
    (folder / "movie.zh.srt").write_text("subtitle")
    (folder / "movie.zh.ffsubsync.srt").write_text("done")
    login(client)

    async def fake_exec(*args, **kwargs):
        output_index = args.index("-o") + 1 if "-o" in args else 3
        Path(args[output_index]).write_text("done")

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

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    client.post(
        "/api/settings/scheduler",
        json={
            "enabled": True,
            "run_on_startup": False,
            "scan_time": "03:00",
            "recursive": True,
            "include_dirs": ["movies"],
            "exclude_dirs": [],
            "enabled_engines": ["ffsubsync", "alass"],
            "engine_options": {
                "ffsubsync_vad": "default",
                "no_fix_framerate": False,
                "gss": False,
                "alass_use_embedded_subtitles": True,
                "alass_disable_fps_guessing": False,
                "alass_disable_speed_optimization": False,
                "alass_split_penalty": 7,
                "autosubsync_use_embedded_subtitles": True,
                "autosubsync_max_shift_secs": 20,
                "autosubsync_parallelism": 3,
            },
        },
    )

    response = client.post("/api/settings/scheduler/run-now")
    assert response.status_code == 200

    for _ in range(30):
        tasks = client.get("/api/tasks").json()["tasks"]
        if tasks:
            break
        time.sleep(0.02)
    tasks = client.get("/api/tasks").json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["sync_tool"] == "alass"
    assert tasks[0]["output_name"] == "movie.zh.alass.srt"
    log = client.get(f"/api/tasks/{tasks[0]['task_id']}/log").json()
    assert "自动扫描已创建同步任务" in log["log"]
