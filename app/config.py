from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_password: str
    secret_key: str
    media_root: Path
    work_root: Path
    port: int = 1314
    max_concurrent_tasks: int = 1
    session_cookie_name: str = "ffsubsync_session"


def load_settings() -> Settings:
    app_password = os.getenv("APP_PASSWORD", "").strip()
    secret_key = os.getenv("SECRET_KEY", "").strip()
    if not app_password:
        raise RuntimeError("APP_PASSWORD must be set")
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be set")

    media_root = Path(os.getenv("MEDIA_ROOT", "/media")).resolve()
    work_root = Path(os.getenv("WORK_ROOT", "/work")).resolve()
    port = int(os.getenv("PORT", "1314"))
    max_concurrent_tasks = int(os.getenv("MAX_CONCURRENT_TASKS", "1"))
    if port != 1314:
        raise RuntimeError("PORT must be 1314 for this deployment")
    if max_concurrent_tasks < 1:
        raise RuntimeError("MAX_CONCURRENT_TASKS must be at least 1")

    return Settings(
        app_password=app_password,
        secret_key=secret_key,
        media_root=media_root,
        work_root=work_root,
        port=port,
        max_concurrent_tasks=max_concurrent_tasks,
    )
