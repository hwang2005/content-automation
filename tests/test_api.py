from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from backend.ai_writer import Analysis, Fact, WritingError, WritingResult
from tests.conftest import REQUEST_HEADERS, memory_app

PASTED_TEXT = "Workshop AI dành cho sinh viên. Thời gian: 09:00 ngày 30/12/2026. Tham dự miễn phí."


def fake_write_result(item):
    return WritingResult(
        format={"id": item["id"], "name": item["name"], "structure": item["structure"]},
        analysis=Analysis(
            format_id=item["id"], reason="Nguồn mô tả hội thảo một buổi.", confidence=0.9,
            facts=[Fact(label="Tên", value="Workshop AI", source_id="source_1", quote="Workshop AI dành cho sinh viên")],
            warnings=["Chưa có đường dẫn đăng ký."],
        ),
        content="🎯 WORKSHOP AI\n\nTham gia tìm hiểu AI cùng cộng đồng sinh viên.",
        warnings=["Chưa có đường dẫn đăng ký."], input_tokens=1200, output_tokens=400,
    )


def test_initial_status_and_static(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/session").json()["authenticated"] is True
    assert client.get("/api/status").json()["database_ready"] is True
    response = client.get("/")
    assert response.status_code == 200
    assert "chất riêng" in response.text
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert client.get("/static/js/app.js").status_code == 200
    assert client.get("/.env").status_code == 404
    assert client.get("/api/projects").headers["cache-control"] == "no-store"


def test_project_crud_and_isolation(client, project, article_format):
    second = client.post("/api/projects", json={"name": "Dự án khác"}).json()
    assert client.get(f"/api/projects/{second['id']}/formats").json() == []
    wrong_path = f"/api/projects/{second['id']}/formats/{article_format['id']}"
    assert client.delete(wrong_path).status_code == 404
    updated = client.put(f"/api/projects/{project['id']}", json={"name": "Tên đã sửa", "description": "Mô tả"})
    assert updated.status_code == 200
    assert updated.json()["format_count"] == 1
    assert len(client.get("/api/projects").json()) == 2


def test_formats_and_starter_pack(client, project):
    path = f"/api/projects/{project['id']}/starter-formats"
    result = client.post(path)
    assert result.status_code == 201
    assert len(result.json()) == 3
    assert client.post(path).status_code == 409
    item = result.json()[0]
    payload = {key: item[key] for key in ["name", "description", "structure", "writing_guide", "samples", "detection_keywords", "is_active"]}
    payload["samples"] = ["Bài mẫu mới 🎯"]
    payload["is_active"] = False
    saved = client.put(f"/api/projects/{project['id']}/formats/{item['id']}", json=payload)
    assert saved.status_code == 200
    assert saved.json()["samples"] == payload["samples"]
    assert saved.json()["is_active"] is False


def test_generate_edit_history_and_deletion(client, project, article_format):
    client.app.state.writer.write = AsyncMock(return_value=fake_write_result(article_format))
    response = client.post("/api/generate", json={
        "project_id": project["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT,
    })
    assert response.status_code == 201, response.text
    post = response.json()
    assert "🎯" in post["generated_content"]
    assert post["sources"][0]["text"] == PASTED_TEXT
    assert post["source_url"] is None
    history = f"/api/projects/{project['id']}/posts"
    assert client.get(history).json()["total"] == 1
    path = f"{history}/{post['id']}"
    edited = client.patch(path, json={"generated_content": "Bài đã sửa ✨"})
    assert edited.json()["generated_content"] == "Bài đã sửa ✨"
    assert edited.json()["original_content"] == post["generated_content"]
    assert edited.json()["format_snapshot"]["name"] == article_format["name"]
    client.delete(f"/api/projects/{project['id']}/formats/{article_format['id']}")
    saved = client.get(path).json()
    assert saved["format_id"] is None
    assert saved["selected_format_name"] == article_format["name"]
    assert client.delete(path).status_code == 204
    assert client.get(history).json()["total"] == 0


def test_project_deletion_cascades(client, project, article_format):
    client.app.state.writer.write = AsyncMock(return_value=fake_write_result(article_format))
    client.post("/api/generate", json={"project_id": project["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT})
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get("/api/projects").json() == []
    assert client.get(f"/api/projects/{project['id']}/posts").status_code == 404


def test_generation_scope_and_no_active_formats(client, project, article_format):
    second = client.post("/api/projects", json={"name": "Không có dạng bài"}).json()
    response = client.post("/api/generate", json={"project_id": second["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT})
    assert response.status_code == 422
    client.app.state.writer.write = AsyncMock(return_value=fake_write_result(article_format))
    response = client.post("/api/generate", json={"project_id": project["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT})
    assert response.status_code == 201
    called_formats = client.app.state.writer.write.await_args.args[1]
    assert [item["id"] for item in called_formats] == [article_format["id"]]


def test_failed_generation_does_not_save_and_releases_slot(client, project, article_format):
    client.app.state.writer.write = AsyncMock(side_effect=WritingError("OpenAI tạm lỗi", 502))
    response = client.post("/api/generate", json={"project_id": project["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT})
    assert response.status_code == 502
    assert client.get(f"/api/projects/{project['id']}/posts").json()["total"] == 0
    assert not client.app.state.generation_slots.locked()


def test_web_url_rejects_facebook_and_private_urls(client, project, article_format):
    for url in ["https://facebook.com/some-post", "http://127.0.0.1/admin", "http://169.254.169.254/latest"]:
        response = client.post("/api/generate", json={"project_id": project["id"], "source_type": "url", "source_url": url})
        assert response.status_code == 422


def test_validation_and_body_limit(client, project):
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422
    assert client.post("/api/projects", json={"name": "Valid", "api_key": "secret"}).status_code == 422
    assert client.post(f"/api/projects/{project['id']}/formats", json={"name": "Test", "structure": "   "}).status_code == 422
    assert client.post("/api/generate", json={"project_id": project["id"], "source_type": "facebook_paste", "source_text": "ngắn"}).status_code == 422
    assert client.post("/api/projects", content="x" * 400001).status_code == 413


def test_missing_key_is_actionable_without_charging():
    with TestClient(memory_app(openai_api_key=""), headers=REQUEST_HEADERS) as client:
        assert client.get("/api/status").json()["openai_ready"] is False
        response = client.post("/api/generate", json={"project_id": "00000000-0000-0000-0000-000000000000", "source_type": "facebook_paste", "source_text": PASTED_TEXT})
        assert response.status_code == 503
        assert "OPENAI_API_KEY" in response.json()["detail"]


def test_authentication_cookie_csrf_and_logout():
    with TestClient(memory_app(app_password="correct-password", session_secret="s" * 48), headers=REQUEST_HEADERS) as client:
        assert client.get("/api/projects").status_code == 401
        assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
        response = client.post("/api/login", json={"password": "correct-password"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert client.get("/api/projects").status_code == 200
        assert client.post("/api/projects", json={"name": "X"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/projects", json={"name": "X"}, headers={"X-Workspace-Request": ""}).status_code == 403
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/projects").status_code == 401


def test_production_fails_closed_and_disables_api_docs():
    with TestClient(memory_app(app_env="production"), headers=REQUEST_HEADERS) as client:
        assert client.get("/api/session").json()["auth_configured"] is False
        assert client.get("/api/projects").status_code == 503
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_login_rate_limit():
    with TestClient(memory_app(app_password="password-test"), headers=REQUEST_HEADERS) as client:
        for _ in range(8):
            assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
        limited = client.post("/api/login", json={"password": "wrong"})
        assert limited.status_code == 429
        assert "retry-after" in limited.headers


def test_generation_rate_limit(client, project, article_format):
    client.app.state.settings.generate_requests_per_hour = 1
    client.app.state.writer.write = AsyncMock(return_value=fake_write_result(article_format))
    payload = {"project_id": project["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT}
    assert client.post("/api/generate", json=payload).status_code == 201
    assert client.post("/api/generate", json=payload).status_code == 429
