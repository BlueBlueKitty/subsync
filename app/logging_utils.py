from __future__ import annotations

import logging


QUIET_ACCESS_LOG_PATHS = (
    "/",
    "/settings",
    "/subtitle-tools",
    "/tasks",
    "/api/tasks",
    "/api/files",
    "/api/subtitles/match",
    "/api/settings/scheduler",
    "/api/settings/scheduler/status",
)


def should_filter_access_log(method: str, path: str, status_code: int | str | None = None) -> bool:
    normalized_method = (method or "").upper()
    normalized_path = (path or "").split("?", 1)[0]
    try:
        normalized_status = int(status_code) if status_code is not None else 0
    except (TypeError, ValueError):
        normalized_status = 0
    if normalized_method != "GET":
        return False
    if normalized_status >= 400:
        return False
    if normalized_path.startswith("/static/"):
        return True
    if normalized_path in QUIET_ACCESS_LOG_PATHS:
        return True
    return normalized_path.startswith("/api/tasks/") and (
        normalized_path.endswith("/log") or normalized_path.count("/") == 3
    )


class PollingAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = getattr(record, "args", ())
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        method = str(args[1])
        path = str(args[2])
        status_code = args[4] if len(args) >= 5 else None
        return not should_filter_access_log(method, path, status_code)


def install_polling_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(existing, PollingAccessLogFilter) for existing in logger.filters):
        return
    logger.addFilter(PollingAccessLogFilter())
