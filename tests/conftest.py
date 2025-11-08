from __future__ import annotations

import pytest

import os

import pytest

from mai.db.session import reset_engine
from mai.db.init import apply_schema
from mai.core.config import get_settings as settings_cache


@pytest.fixture(autouse=True, scope="session")
def disable_watcher_env():
    os.environ.setdefault("MAI_DISABLE_WATCHER", "1")
    os.environ.setdefault("DISABLE_WATCHER", "1")
    yield


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("MAI_DB_PATH", str(db_path))
    settings_cache.cache_clear()
    reset_engine()
    apply_schema()
    yield str(db_path)
    reset_engine()
    settings_cache.cache_clear()
