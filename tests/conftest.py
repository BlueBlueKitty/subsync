from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    media_root = tmp_path / "media"
    data_root = tmp_path / "data"
    media_root.mkdir()
    settings = Settings(
        app_password="secret",
        secret_key="test-secret",
        media_root=media_root,
        data_root=data_root,
        port=1314,
        max_concurrent_tasks=1,
    )
    settings.ensure_directories()
    return settings


@pytest.fixture()
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
