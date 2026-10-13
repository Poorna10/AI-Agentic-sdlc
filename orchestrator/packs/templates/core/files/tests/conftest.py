import pytest
from fastapi.testclient import TestClient

from shortener.api import create_app
from shortener.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), follow_redirects=False) as c:
        yield c
