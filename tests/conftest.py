from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    media_root = tmp_path / "media"
    work_root = tmp_path / "work"
    media_root.mkdir()
    work_root.mkdir()
    return Settings(
        app_password="secret",
        secret_key="test-secret",
        media_root=media_root,
        work_root=work_root,
        port=1314,
        max_concurrent_tasks=1,
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    return TestClient(app)
