import os
os.environ['MODEL_PROVIDER']='mock'
import pytest
from backend.store import Store

@pytest.fixture
def store(tmp_path):return Store(tmp_path/'test.sqlite3')

@pytest.fixture
def client(tmp_path,monkeypatch):
    from backend import tools
    test_store=Store(tmp_path/'api.sqlite3')
    monkeypatch.setattr(tools,'store',test_store)
    from backend import app as app_module
    monkeypatch.setattr(app_module,'store',test_store)
    app=app_module.app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:yield c

