from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Settings:
    app_password: str
    secret_key: str
    media_root: Path
    data_root: Path
    port: int = 1314
    max_concurrent_tasks: int = 1
    session_cookie_name: str = "subsync_session"
    timezone_name: str = "UTC"
    quiet_polling_access_logs: bool = True

    @property
    def config_dir(self) -> Path:
        return self.data_root / "config"

    @property
    def uploads_dir(self) -> Path:
        return self.data_root / "uploads"

    @property
    def runtime_dir(self) -> Path:
        return self.data_root / "runtime"

    @property
    def temp_dir(self) -> Path:
        return self.data_root / "tmp"

    @property
    def timezone(self) -> tzinfo:
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            return timezone.utc

    def ensure_directories(self) -> None:
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    def _parse_bool(value: str | None, default: bool) -> bool:
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    app_password = os.getenv("APP_PASSWORD", "").strip()
    secret_key = os.getenv("SECRET_KEY", "").strip()
    if not app_password:
        raise RuntimeError("APP_PASSWORD must be set")
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be set")

    media_root = Path(os.getenv("MEDIA_ROOT", "/media")).resolve()
    data_root = Path(os.getenv("DATA_ROOT", "/data")).resolve()
    timezone_name = os.getenv("TZ", "UTC").strip() or "UTC"
    port = int(os.getenv("PORT", "1314"))
    max_concurrent_tasks = int(os.getenv("MAX_CONCURRENT_TASKS", "1"))
    quiet_polling_access_logs = _parse_bool(os.getenv("QUIET_POLLING_ACCESS_LOGS"), True)
    if port != 1314:
        raise RuntimeError("PORT must be 1314 for this deployment")
    if max_concurrent_tasks < 1:
        raise RuntimeError("MAX_CONCURRENT_TASKS must be at least 1")

    settings = Settings(
        app_password=app_password,
        secret_key=secret_key,
        media_root=media_root,
        data_root=data_root,
        port=port,
        max_concurrent_tasks=max_concurrent_tasks,
        timezone_name=timezone_name,
        quiet_polling_access_logs=quiet_polling_access_logs,
    )
    settings.ensure_directories()
    return settings
