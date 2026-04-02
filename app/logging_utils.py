from __future__ import annotations

import logging


QUIET_ACCESS_LOG_PATHS = (
    "/api/tasks",
    "/api/settings/scheduler/status",
)


def should_filter_access_log(method: str, path: str) -> bool:
    normalized_method = (method or "").upper()
    normalized_path = (path or "").split("?", 1)[0]
    if normalized_method != "GET":
        return False
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
        return not should_filter_access_log(method, path)


def install_polling_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(existing, PollingAccessLogFilter) for existing in logger.filters):
        return
    logger.addFilter(PollingAccessLogFilter())
