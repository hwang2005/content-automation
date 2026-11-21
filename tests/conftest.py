import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from backend.config import Settings
from backend.main import create_app

REQUEST_HEADERS = {"X-Workspace-Request": "1"}


def memory_app(**overrides):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    values = {
        "app_env": "development", "app_password": "", "session_secret": "",
        "database_url": "", "openai_api_key": "sk-test-not-a-real-key",
        "openai_base_url": "", "openai_api_mode": "auto",
        "openai_response_format": "json_schema", "openai_chat_token_parameter": "max_tokens",
    }
    values.update(overrides)
    return create_app(Settings(_env_file=None, **values), engine=engine)


@pytest.fixture
def client():
    with TestClient(memory_app(), headers=REQUEST_HEADERS) as test_client:
        yield test_client


@pytest.fixture
def project(client):
    response = client.post("/api/projects", json={"name": "Dự án kiểm thử", "writing_guide": "Thân thiện, không bịa thông tin."})
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def article_format(client, project):
    response = client.post(f"/api/projects/{project['id']}/formats", json={
        "name": "Hội thảo", "description": "Dùng cho hội thảo một buổi.",
        "structure": "Tiêu đề → thời gian → đăng ký", "writing_guide": "Dùng emoji vừa phải.",
        "samples": ["🎯 Đây là bài mẫu, không phải dữ kiện nguồn."],
        "detection_keywords": ["workshop"],
    })
    assert response.status_code == 201
    return response.json()
