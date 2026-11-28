from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from backend.ai_writer import Analysis, Fact, WritingError, WritingResult
from backend.auth import OAuthExchangeError
from backend.database import ensure_sqlite_schema
from tests.conftest import REQUEST_HEADERS, memory_app

PASTED_TEXT = "Workshop AI dành cho sinh viên. Thời gian: 09:00 ngày 30/12/2026. Tham dự miễn phí."


def test_database_error_is_distinguished_from_ai_503(client, project, article_format, caplog):
    client.app.state.writer.write = AsyncMock(side_effect=SQLAlchemyError("PRIVATE DB credentials"))
    response = client.post("/api/generate", json={
        "project_id": project["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT,
    })
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "PRIVATE" not in response.text + caplog.text
    assert not client.app.state.generation_slots.locked()


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


def test_status_shows_ai_protocol_without_exposing_provider_secrets():
    with TestClient(memory_app(
        openai_base_url="https://private-provider.example/tenant-private/v1",
        openai_api_key="sk-private-provider-key", openai_response_format="json_object",
        openai_model="provider-model",
    ), headers=REQUEST_HEADERS) as client:
        response = client.get("/api/status")
        data = response.json()
        assert data["ai_provider"] == "OpenAI-compatible"
        assert data["ai_api_mode"] == "chat_completions"
        assert data["ai_response_format"] == "json_object"
        assert data["model"] == "provider-model"
        assert data["openai_ready"] is True
        assert "private-provider" not in response.text
        assert "tenant-private" not in response.text


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


def test_generation_exposes_safe_error_code_and_logs_cause(client, project, article_format, caplog):
    client.app.state.writer.write = AsyncMock(side_effect=WritingError(
        "Nhà cung cấp từ chối xác thực.", 503,
        code="AI_AUTHENTICATION_FAILED", upstream_status=401,
    ))
    response = client.post("/api/generate", json={
        "project_id": project["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT,
    })
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Nhà cung cấp từ chối xác thực.",
        "code": "AI_AUTHENTICATION_FAILED", "upstream_status": 401,
    }
    assert "upstream_status=401" in caplog.text
    assert "AI_AUTHENTICATION_FAILED" in caplog.text
    assert "sk-test-not-a-real-key" not in caplog.text
    assert client.get(f"/api/projects/{project['id']}/posts").json()["total"] == 0


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
        assert "httponly" in cookie and "samesite=lax" in cookie
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


def _login_google(client: TestClient, user_id: str, email: str, name: str = "Google User"):
    client.app.state.exchange_supabase_pkce = AsyncMock(
        return_value={"id": user_id, "email": email, "name": name, "email_verified": True}
    )
    start = client.get("/auth/google", follow_redirects=False)
    assert start.status_code == 302
    callback = client.get("/auth/callback?code=valid-auth-code", follow_redirects=False)
    assert callback.status_code == 302
    assert callback.headers["location"] == "/"
    return start, callback


def test_google_oauth_login_flow_and_session_status():
    app = memory_app(
        app_env="production",
        session_secret="s" * 48,
        supabase_url="https://demo.supabase.co",
        supabase_anon_key="anon-test-key",
        app_origin="https://studio.example.com",
    )
    with TestClient(app, base_url="https://testserver", headers=REQUEST_HEADERS) as client:
        session = client.get("/api/session").json()
        assert session["authenticated"] is False
        assert session["auth_configured"] is True
        assert session["google_oauth_enabled"] is True
        assert session["password_enabled"] is False
        assert client.post("/api/login", json={"password": "anything"}).status_code == 400

        start, callback = _login_google(client, "user-123", "alice@example.com", "Alice")
        location = urlsplit(start.headers["location"])
        assert f"{location.scheme}://{location.netloc}{location.path}" == "https://demo.supabase.co/auth/v1/authorize"
        params = parse_qs(location.query)
        assert params["provider"] == ["google"]
        assert params["redirect_to"] == ["https://studio.example.com/auth/callback"]
        assert params["code_challenge_method"] == ["s256"]
        assert "httponly" in start.headers["set-cookie"].lower()
        assert "secure" in start.headers["set-cookie"].lower()
        assert "samesite=lax" in callback.headers["set-cookie"].lower()

        session_after = client.get("/api/session").json()
        assert session_after["authenticated"] is True
        assert session_after["user"] == {"auth_method": "google", "email": "alice@example.com", "name": "Alice"}
        status = client.get("/api/status").json()
        assert status["auth_method"] == "google"
        assert status["user_email"] == "alice@example.com"
        assert status["google_oauth_enabled"] is True


def test_per_account_project_isolation_between_google_and_password_users():
    app = memory_app(
        app_env="production",
        app_password="workspace-password-123",
        session_secret="s" * 48,
        supabase_url="https://demo.supabase.co",
        supabase_anon_key="anon-test-key",
        app_origin="https://studio.example.com",
    )
    with (
        TestClient(app, base_url="https://testserver", headers=REQUEST_HEADERS) as user_a,
        TestClient(app, base_url="https://testserver", headers=REQUEST_HEADERS) as user_b,
        TestClient(app, base_url="https://testserver", headers=REQUEST_HEADERS) as pw_user,
    ):
        assert user_a.get("/api/session").json()["password_enabled"] is True
        assert user_a.get("/api/session").json()["google_oauth_enabled"] is True

        _login_google(user_a, "uid-a", "a@example.com", "Alice")
        _login_google(user_b, "uid-b", "b@example.com", "Bob")
        assert pw_user.post("/api/login", json={"password": "workspace-password-123"}).status_code == 200

        project_a = user_a.post("/api/projects", json={"name": "Dự án của Alice"}).json()
        format_a = user_a.post(
            f"/api/projects/{project_a['id']}/formats",
            json={"name": "Tin tức", "structure": "Tiêu đề → nội dung"},
        ).json()
        app.state.writer.write = AsyncMock(return_value=fake_write_result(format_a))
        post_a = user_a.post(
            "/api/generate",
            json={"project_id": project_a["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT},
        ).json()

        project_pw = pw_user.post("/api/projects", json={"name": "Dự án chung"}).json()

        assert [p["id"] for p in user_a.get("/api/projects").json()] == [project_a["id"]]
        assert user_b.get("/api/projects").json() == []
        assert [p["id"] for p in pw_user.get("/api/projects").json()] == [project_pw["id"]]

        for other in (user_b, pw_user):
            assert other.put(f"/api/projects/{project_a['id']}", json={"name": "Hack"}).status_code == 404
            assert other.delete(f"/api/projects/{project_a['id']}").status_code == 404
            assert other.get(f"/api/projects/{project_a['id']}/formats").status_code == 404
            assert other.put(
                f"/api/projects/{project_a['id']}/formats/{format_a['id']}",
                json={"name": "Hack", "structure": "X"},
            ).status_code == 404
            assert other.delete(f"/api/projects/{project_a['id']}/formats/{format_a['id']}").status_code == 404
            assert other.get(f"/api/projects/{project_a['id']}/posts").status_code == 404
            assert other.get(f"/api/projects/{project_a['id']}/posts/{post_a['id']}").status_code == 404
            assert other.patch(
                f"/api/projects/{project_a['id']}/posts/{post_a['id']}",
                json={"generated_content": "Hack"},
            ).status_code == 404
            assert other.post(
                "/api/generate",
                json={"project_id": project_a["id"], "source_type": "facebook_paste", "source_text": PASTED_TEXT},
            ).status_code == 404

        assert user_a.get(f"/api/projects/{project_pw['id']}/formats").status_code == 404


def test_google_oauth_callback_errors_and_allowlist():
    app = memory_app(
        app_env="production",
        session_secret="s" * 48,
        supabase_url="https://demo.supabase.co",
        supabase_anon_key="anon-test-key",
        allowed_emails="allowed@example.com",
    )
    with TestClient(app, base_url="https://testserver", headers=REQUEST_HEADERS) as client:
        assert client.get("/auth/callback?code=abc", follow_redirects=False).headers["location"] == "/?auth_error=oauth_state_expired"

        client.get("/auth/google", follow_redirects=False)
        assert client.get("/auth/callback?error=access_denied", follow_redirects=False).headers["location"] == "/?auth_error=oauth_cancelled"

        client.get("/auth/google", follow_redirects=False)
        assert client.get("/auth/callback", follow_redirects=False).headers["location"] == "/?auth_error=oauth_invalid_callback"

        client.get("/auth/google", follow_redirects=False)
        app.state.exchange_supabase_pkce = AsyncMock(side_effect=OAuthExchangeError("oauth_exchange_failed"))
        assert client.get("/auth/callback?code=bad", follow_redirects=False).headers["location"] == "/?auth_error=oauth_exchange_failed"

        client.get("/auth/google", follow_redirects=False)
        app.state.exchange_supabase_pkce = AsyncMock(
            return_value={"id": "u1", "email": "allowed@example.com", "name": "Allowed", "email_verified": False}
        )
        assert client.get("/auth/callback?code=unverified", follow_redirects=False).headers["location"] == "/?auth_error=email_unverified"

        client.get("/auth/google", follow_redirects=False)
        app.state.exchange_supabase_pkce = AsyncMock(
            return_value={"id": "u2", "email": "stranger@example.com", "name": "Stranger", "email_verified": True}
        )
        assert client.get("/auth/callback?code=blocked", follow_redirects=False).headers["location"] == "/?auth_error=email_not_allowed"
        assert client.get("/api/session").json()["authenticated"] is False

        client.get("/auth/google", follow_redirects=False)
        app.state.exchange_supabase_pkce = AsyncMock(
            return_value={"id": "u1", "email": "Allowed@Example.com", "name": "Allowed", "email_verified": True}
        )
        assert client.get("/auth/callback?code=ok", follow_redirects=False).headers["location"] == "/"
        assert client.get("/api/session").json()["authenticated"] is True


def test_sqlite_schema_upgrade_adds_owner_id_with_workspace_default():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE projects (id CHAR(32) PRIMARY KEY, name VARCHAR(120) NOT NULL, "
            "description TEXT NOT NULL DEFAULT '', writing_guide TEXT NOT NULL DEFAULT '')"
        )
        connection.exec_driver_sql("INSERT INTO projects (id, name) VALUES ('11111111111111111111111111111111', 'Old')")
    ensure_sqlite_schema(engine)
    with engine.connect() as connection:
        owner = connection.execute(text("SELECT owner_id FROM projects WHERE name = 'Old'")).scalar_one()
        assert owner == "workspace"
