from __future__ import annotations

import asyncio
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.models import CreateTaskRequest, SchedulerConfig, SchedulerStateResponse, SchedulerStatus, SyncTool
from app.services.files import build_engine_output_name, discover_scan_candidates, validate_media_file
from app.services.tasks import TaskManager


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_scan_time(scan_time: str) -> time:
    hour_text, minute_text = scan_time.split(":")
    return time(hour=int(hour_text), minute=int(minute_text))


class SchedulerService:
    def __init__(self, settings: Settings, task_manager: TaskManager) -> None:
        self._settings = settings
        self._task_manager = task_manager
        self._config_path = settings.config_dir / "scheduler.json"
        self._status_path = settings.runtime_dir / "scheduler_status.json"
        self._config = self._load_config()
        self._status = self._load_status()
        self._scan_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None

    def _load_config(self) -> SchedulerConfig:
        if self._config_path.exists():
            return SchedulerConfig.model_validate_json(self._config_path.read_text(encoding="utf-8"))
        config = SchedulerConfig()
        self._save_config(config)
        return config

    def _save_config(self, config: SchedulerConfig) -> None:
        self._config_path.write_text(
            json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_status(self) -> SchedulerStatus:
        if self._status_path.exists():
            return SchedulerStatus.model_validate_json(self._status_path.read_text(encoding="utf-8"))
        status = SchedulerStatus()
        self._save_status(status)
        return status

    def _save_status(self, status: SchedulerStatus) -> None:
        self._status_path.write_text(
            json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_state(self) -> SchedulerStateResponse:
        return SchedulerStateResponse(config=self._config, status=self._status)

    async def update_config(self, config: SchedulerConfig) -> SchedulerStateResponse:
        self._config = config
        self._save_config(config)
        await self.restart(run_startup_scan=False)
        return self.get_state()

    async def start(self, run_startup_scan: bool = True) -> None:
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._run_loop())
        if run_startup_scan and self._config.enabled and self._config.run_on_startup:
            loop = asyncio.get_running_loop()
            loop.call_soon(lambda: asyncio.create_task(self.run_scan("startup")))

    async def stop(self) -> None:
        self._stop_event.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def restart(self, run_startup_scan: bool = True) -> None:
        await self.stop()
        await self.start(run_startup_scan=run_startup_scan)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            config = self._config
            if not config.enabled:
                await asyncio.sleep(2)
                continue
            await self._sleep_until_next_scan(config.scan_time)
            if self._stop_event.is_set():
                break
            await self.run_scan("scheduled")

    async def _sleep_until_next_scan(self, scan_time: str) -> None:
        now_local = datetime.now(self._settings.timezone)
        target_time = _parse_scan_time(scan_time)
        next_run = datetime.combine(now_local.date(), target_time, tzinfo=self._settings.timezone)
        if next_run <= now_local:
            next_run = next_run + timedelta(days=1)
        sleep_seconds = max((next_run - now_local).total_seconds(), 1)
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_seconds)
        except asyncio.TimeoutError:
            return

    def _build_request(self, sync_tool: SyncTool) -> CreateTaskRequest:
        options = self._config.engine_options
        return CreateTaskRequest(
            sync_tool=sync_tool,
            video_path="__scheduled_video__",
            subtitle_path="__scheduled_subtitle__",
            ffsubsync_use_embedded_subtitles=options.ffsubsync_use_embedded_subtitles,
            ffsubsync_vad=options.ffsubsync_vad,
            no_fix_framerate=options.no_fix_framerate,
            gss=options.gss,
            alass_use_embedded_subtitles=options.alass_use_embedded_subtitles,
            alass_disable_fps_guessing=options.alass_disable_fps_guessing,
            alass_disable_speed_optimization=options.alass_disable_speed_optimization,
            alass_split_penalty=options.alass_split_penalty,
            autosubsync_use_embedded_subtitles=options.autosubsync_use_embedded_subtitles,
            autosubsync_max_shift_secs=options.autosubsync_max_shift_secs,
            autosubsync_parallelism=options.autosubsync_parallelism,
        )

    async def run_scan(self, trigger: str) -> SchedulerStatus:
        if self._scan_lock.locked():
            self._status.last_status = "skipped"
            self._status.last_summary = f"{trigger} 触发时已有扫描正在运行，已跳过"
            self._save_status(self._status)
            return self._status

        async with self._scan_lock:
            started_at = _utc_now()
            self._status.is_running = True
            self._status.last_started_at = started_at
            self._status.last_status = "running"
            self._status.last_summary = f"开始执行 {trigger} 扫描"
            self._status.last_error = None
            self._save_status(self._status)

            try:
                candidates = await asyncio.to_thread(
                    discover_scan_candidates,
                    self._settings,
                    self._config.include_dirs,
                    self._config.exclude_dirs,
                    self._config.recursive,
                )
                created_count = 0
                skipped_count = 0
                unmatched_count = 0

                for candidate in candidates:
                    subtitle_path = candidate["subtitle_path"]
                    video_path = candidate["video_path"]
                    video_real_path = validate_media_file(self._settings, video_path, "video")
                    subtitle_real_path = validate_media_file(self._settings, subtitle_path, "subtitle")
                    engine_created = False
                    for sync_tool in self._config.enabled_engines:
                        output_path = video_real_path.parent / build_engine_output_name(subtitle_real_path.name, sync_tool)
                        if output_path.exists():
                            skipped_count += 1
                            continue
                        payload = self._build_request(sync_tool)
                        await self._task_manager.create_task(
                            payload,
                            video_real_path,
                            subtitle_real_path,
                            output_path,
                            "scheduled",
                        )
                        created_count += 1
                        engine_created = True
                    if not engine_created:
                        unmatched_count += 0

                self._status.last_status = "succeeded"
                self._status.last_summary = (
                    f"{trigger} 扫描完成：找到 {len(candidates)} 组候选，创建 {created_count} 个任务，"
                    f"跳过 {skipped_count} 个已存在输出"
                )
                self._status.last_error = None
            except Exception as exc:
                self._status.last_status = "failed"
                self._status.last_summary = f"{trigger} 扫描失败"
                self._status.last_error = str(exc)
            finally:
                self._status.is_running = False
                self._status.last_finished_at = _utc_now()
                self._save_status(self._status)
            return self._status

    async def trigger_run_now(self) -> SchedulerStatus:
        if self._scan_lock.locked():
            self._status.last_status = "skipped"
            self._status.last_summary = "手动触发扫描时已有扫描正在运行，已跳过"
            self._save_status(self._status)
            return self._status
        self._status.is_running = True
        self._status.last_status = "running"
        self._status.last_summary = "已手动触发扫描"
        self._status.last_error = None
        self._save_status(self._status)
        asyncio.create_task(self.run_scan("manual"))
        return self._status
