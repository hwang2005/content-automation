import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.ai_writer import AIWriter, WritingError
from backend.auth import (
    COOKIE_NAME,
    OAUTH_COOKIE_NAME,
    OAUTH_STATE_SECONDS,
    SESSION_SECONDS,
    AuthUser,
    OAuthExchangeError,
    RateLimiter,
    check_password,
    create_google_session_token,
    create_password_session_token,
    current_user,
    exchange_supabase_pkce,
    generate_pkce,
    oauth_flow_signer,
    require_auth,
)
from backend.config import Settings, get_settings
from backend.database import ensure_sqlite_schema, make_engine, session_factory
from backend.extractor import ExtractionError, extract_website, pasted_source
from backend.models import ArticleFormat, Base, GeneratedPost, Project
from backend.schemas import (
    FormatInput,
    FormatOut,
    GenerateInput,
    LoginInput,
    PostEdit,
    PostOut,
    PostPage,
    ProjectInput,
    ProjectOut,
)

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("content_studio")


def db_session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def project_or_404(session: Session, project_id: UUID, owner_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project or project.owner_id != owner_id:
        raise HTTPException(404, "Không tìm thấy dự án.")
    return project


def format_or_404(session: Session, project_id: UUID, format_id: UUID, owner_id: str) -> ArticleFormat:
    project_or_404(session, project_id, owner_id)
    item = session.get(ArticleFormat, format_id)
    if not item or item.project_id != project_id:
        raise HTTPException(404, "Không tìm thấy dạng bài trong dự án này.")
    return item


def post_or_404(session: Session, project_id: UUID, post_id: UUID, owner_id: str) -> GeneratedPost:
    project_or_404(session, project_id, owner_id)
    item = session.get(GeneratedPost, post_id)
    if not item or item.project_id != project_id:
        raise HTTPException(404, "Không tìm thấy bài viết trong dự án này.")
    return item


def project_out(session: Session, project: Project) -> ProjectOut:
    result = ProjectOut.model_validate(project)
    result.format_count = session.scalar(select(func.count()).select_from(ArticleFormat).where(ArticleFormat.project_id == project.id)) or 0
    result.post_count = session.scalar(select(func.count()).select_from(GeneratedPost).where(GeneratedPost.project_id == project.id)) or 0
    return result


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    settings = settings or get_settings()
    engine = engine if engine is not None else make_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Only local SQLite is bootstrapped here. PostgreSQL uses versioned migrations.
        if engine.dialect.name == "sqlite":
            Base.metadata.create_all(engine)
            ensure_sqlite_schema(engine)
        yield
        await app.state.writer.close()
        engine.dispose()

    app = FastAPI(
        title="Content Studio", lifespan=lifespan,
        docs_url=None if settings.production else "/docs",
        redoc_url=None, openapi_url=None if settings.production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory(engine)
    app.state.local_session_secret = secrets.token_urlsafe(48)
    app.state.limiter = RateLimiter()
    app.state.generation_slots = asyncio.Semaphore(settings.max_concurrent_generations)
    app.state.writer = AIWriter(settings)
    app.state.exchange_supabase_pkce = exchange_supabase_pkce

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
            # This custom header cannot be sent cross-origin without a preflight.
            # No CORS middleware is enabled; additionally validate a present Origin.
            if request.headers.get("X-Workspace-Request") != "1":
                return JSONResponse({"detail": "Yêu cầu thiếu thông tin bảo vệ CSRF."}, status_code=403)
            origin = request.headers.get("origin")
            allowed = settings.app_origin.rstrip("/") or str(request.base_url).rstrip("/")
            if origin and origin != allowed:
                return JSONResponse({"detail": "Nguồn yêu cầu không hợp lệ."}, status_code=403)
        if request.url.path.startswith("/api/"):
            try:
                declared = int(request.headers.get("content-length", "0"))
            except ValueError:
                declared = 999999
            if declared > 400000:
                return JSONResponse({"detail": "Nội dung yêu cầu quá lớn (tối đa 400 KB)."}, status_code=413)
            # Also enforce for chunked bodies (Content-Length may be absent/untrusted).
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 400000:
                    return JSONResponse({"detail": "Nội dung yêu cầu quá lớn (tối đa 400 KB)."}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, error):
        messages = []
        for issue in error.errors()[:5]:
            field = ".".join(str(part) for part in issue["loc"] if part != "body")
            messages.append(f"{field}: {issue['msg']}" if field else issue["msg"])
        # Do not echo request bodies (they can include the login password).
        return JSONResponse({"detail": "Dữ liệu chưa hợp lệ. " + "; ".join(messages)}, status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_, error):
        logger.error("Database operation failed code=DATABASE_UNAVAILABLE type=%s", type(error).__name__)
        return JSONResponse({"detail": "Không thể lưu/đọc dữ liệu. Kiểm tra kết nối Supabase và migration, sau đó thử lại.", "code": "DATABASE_UNAVAILABLE"}, status_code=503)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/session")
    def session_status(request: Request):
        user = current_user(request)
        return {
            "authenticated": user is not None,
            "login_required": settings.login_required,
            "password_required": settings.password_auth_enabled,
            "password_enabled": settings.password_auth_enabled,
            "google_oauth_enabled": settings.google_oauth_enabled,
            "auth_configured": settings.auth_ready,
            "app_name": settings.app_name,
            "user": (
                {"auth_method": user.auth_method, "email": user.email, "name": user.name}
                if user
                else None
            ),
        }

    @app.post("/api/login")
    def login(payload: LoginInput, request: Request, response: Response):
        if not settings.auth_ready:
            raise HTTPException(503, "Chưa cấu hình mật khẩu và khóa phiên an toàn trên máy chủ.")
        if not settings.password_auth_enabled:
            raise HTTPException(400, "Đăng nhập bằng mật khẩu chưa được bật. Vui lòng dùng Google.")
        client = request.client.host if request.client else "unknown"
        app.state.limiter.check("login:" + client, 8, 300)
        if not check_password(request, payload.password):
            raise HTTPException(401, "Mật khẩu không chính xác.")
        response.set_cookie(
            COOKIE_NAME,
            create_password_session_token(request),
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=settings.production,
            samesite="lax",
        )
        return {"authenticated": True}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE_NAME, secure=settings.production, httponly=True, samesite="lax")
        return {"authenticated": False}

    @app.get("/auth/google", include_in_schema=False)
    def google_oauth_start(request: Request):
        if not settings.google_oauth_enabled or not settings.auth_ready:
            return RedirectResponse("/?auth_error=oauth_not_configured", status_code=302)
        client = request.client.host if request.client else "unknown"
        app.state.limiter.check("oauth:" + client, 20, 300)
        base = settings.app_origin.rstrip("/") or str(request.base_url).rstrip("/")
        verifier, challenge = generate_pkce()
        query = urlencode({
            "provider": "google",
            "redirect_to": f"{base}/auth/callback",
            "code_challenge": challenge,
            "code_challenge_method": "s256",
        })
        response = RedirectResponse(f"{settings.supabase_url}/auth/v1/authorize?{query}", status_code=302)
        response.set_cookie(
            OAUTH_COOKIE_NAME,
            oauth_flow_signer(request).dumps({"verifier": verifier, "nonce": secrets.token_hex(16)}),
            max_age=OAUTH_STATE_SECONDS,
            httponly=True,
            secure=settings.production,
            samesite="lax",
            path="/auth/callback",
        )
        return response

    @app.get("/auth/callback", include_in_schema=False)
    async def google_oauth_callback(request: Request):
        def fail(code: str) -> RedirectResponse:
            response = RedirectResponse(f"/?auth_error={code}", status_code=302)
            response.delete_cookie(
                OAUTH_COOKIE_NAME,
                path="/auth/callback",
                secure=settings.production,
                httponly=True,
                samesite="lax",
            )
            return response

        if not settings.google_oauth_enabled or not settings.auth_ready:
            return fail("oauth_not_configured")
        if request.query_params.get("error"):
            return fail("oauth_cancelled")
        code = request.query_params.get("code", "").strip()
        if not code:
            return fail("oauth_invalid_callback")
        raw_flow = request.cookies.get(OAUTH_COOKIE_NAME, "")
        if not raw_flow:
            return fail("oauth_state_expired")
        try:
            flow = oauth_flow_signer(request).loads(raw_flow, max_age=OAUTH_STATE_SECONDS)
            verifier = str(flow.get("verifier") or "")
        except (BadSignature, SignatureExpired):
            return fail("oauth_state_expired")
        if not verifier:
            return fail("oauth_state_expired")
        try:
            user_info = await app.state.exchange_supabase_pkce(settings, code, verifier)
        except OAuthExchangeError as error:
            logger.warning("Google OAuth callback failed code=%s", error.code)
            return fail("oauth_exchange_failed")
        if not user_info.get("email_verified"):
            return fail("email_unverified")
        email = str(user_info.get("email") or "").strip()
        if settings.allowed_email_set and email.lower() not in settings.allowed_email_set:
            return fail("email_not_allowed")

        response = RedirectResponse("/", status_code=302)
        response.delete_cookie(
            OAUTH_COOKIE_NAME,
            path="/auth/callback",
            secure=settings.production,
            httponly=True,
            samesite="lax",
        )
        response.set_cookie(
            COOKIE_NAME,
            create_google_session_token(request, str(user_info["id"]), email, str(user_info["name"])),
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=settings.production,
            samesite="lax",
        )
        return response

    api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

    @api.get("/status")
    def status(user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        db_ready = True
        try:
            session.execute(select(Project.id).limit(1))
        except SQLAlchemyError:
            session.rollback()
            db_ready = False
        return {
            "database_ready": db_ready,
            "database_type": "Supabase / PostgreSQL" if engine.dialect.name == "postgresql" else "SQLite (local)",
            "openai_ready": bool(settings.ai_api_key.get_secret_value()),
            "ai_provider": {"groq": "Groq", "gemini": "Gemini (Google AI Studio)"}.get(settings.ai_provider, "OpenAI" if settings.ai_base_url == "https://api.openai.com/v1" else "OpenAI-compatible"),
            "ai_api_mode": settings.ai_api_mode,
            "ai_response_format": settings.ai_response_format,
            "model": settings.ai_model,
            "environment": settings.app_env,
            "password_enabled": settings.password_auth_enabled,
            "google_oauth_enabled": settings.google_oauth_enabled,
            "auth_method": user.auth_method,
            "user_email": user.email,
            "allowed_emails_restricted": bool(settings.allowed_email_set),
        }

    @api.get("/projects", response_model=list[ProjectOut])
    def list_projects(user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        return [
            project_out(session, item)
            for item in session.scalars(select(Project).where(Project.owner_id == user.owner_id).order_by(Project.created_at))
        ]

    @api.post("/projects", response_model=ProjectOut, status_code=201)
    def create_project(payload: ProjectInput, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        item = Project(owner_id=user.owner_id, **payload.model_dump())
        session.add(item)
        session.commit()
        return project_out(session, item)

    @api.put("/projects/{project_id}", response_model=ProjectOut)
    def update_project(project_id: UUID, payload: ProjectInput, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        item = project_or_404(session, project_id, user.owner_id)
        for key, value in payload.model_dump().items():
            setattr(item, key, value)
        session.commit()
        return project_out(session, item)

    @api.delete("/projects/{project_id}", status_code=204)
    def delete_project(project_id: UUID, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        item = project_or_404(session, project_id, user.owner_id)
        session.delete(item)
        session.commit()
        return Response(status_code=204)

    @api.get("/projects/{project_id}/formats", response_model=list[FormatOut])
    def list_formats(project_id: UUID, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        project_or_404(session, project_id, user.owner_id)
        return list(session.scalars(select(ArticleFormat).where(ArticleFormat.project_id == project_id).order_by(ArticleFormat.created_at)))

    @api.post("/projects/{project_id}/formats", response_model=FormatOut, status_code=201)
    def create_format(project_id: UUID, payload: FormatInput, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        project_or_404(session, project_id, user.owner_id)
        count = session.scalar(select(func.count()).select_from(ArticleFormat).where(ArticleFormat.project_id == project_id)) or 0
        if count >= 30:
            raise HTTPException(422, "Mỗi dự án hiện hỗ trợ tối đa 30 dạng bài.")
        item = ArticleFormat(project_id=project_id, **payload.model_dump())
        session.add(item)
        session.commit()
        return item

    @api.put("/projects/{project_id}/formats/{format_id}", response_model=FormatOut)
    def update_format(project_id: UUID, format_id: UUID, payload: FormatInput, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        item = format_or_404(session, project_id, format_id, user.owner_id)
        for key, value in payload.model_dump().items():
            setattr(item, key, value)
        session.commit()
        return item

    @api.delete("/projects/{project_id}/formats/{format_id}", status_code=204)
    def delete_format(project_id: UUID, format_id: UUID, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        item = format_or_404(session, project_id, format_id, user.owner_id)
        session.delete(item)
        session.commit()
        return Response(status_code=204)

    @api.post("/projects/{project_id}/starter-formats", response_model=list[FormatOut], status_code=201)
    def starter_formats(project_id: UUID, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        project_or_404(session, project_id, user.owner_id)
        if session.scalar(select(ArticleFormat.id).where(ArticleFormat.project_id == project_id).limit(1)):
            raise HTTPException(409, "Chỉ thêm bộ gợi ý khi dự án chưa có dạng bài.")
        data = json.loads((ROOT / "kb" / "starter_formats.json").read_text(encoding="utf-8"))
        items = [ArticleFormat(project_id=project_id, **FormatInput.model_validate(row).model_dump()) for row in data]
        session.add_all(items)
        session.commit()
        return items

    @api.get("/projects/{project_id}/posts", response_model=PostPage)
    def history(project_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=50), user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        project_or_404(session, project_id, user.owner_id)
        query = select(GeneratedPost).where(GeneratedPost.project_id == project_id)
        total = session.scalar(select(func.count()).select_from(GeneratedPost).where(GeneratedPost.project_id == project_id)) or 0
        items = session.scalars(query.order_by(GeneratedPost.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
        return PostPage(items=items, total=total, page=page, page_size=page_size)

    @api.get("/projects/{project_id}/posts/{post_id}", response_model=PostOut)
    def get_post(project_id: UUID, post_id: UUID, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        return post_or_404(session, project_id, post_id, user.owner_id)

    @api.patch("/projects/{project_id}/posts/{post_id}", response_model=PostOut)
    def edit_post(project_id: UUID, post_id: UUID, payload: PostEdit, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        item = post_or_404(session, project_id, post_id, user.owner_id)
        item.generated_content = payload.generated_content
        session.commit()
        return item

    @api.delete("/projects/{project_id}/posts/{post_id}", status_code=204)
    def delete_post(project_id: UUID, post_id: UUID, user: AuthUser = Depends(require_auth), session: Session = Depends(db_session)):
        session.delete(post_or_404(session, project_id, post_id, user.owner_id))
        session.commit()
        return Response(status_code=204)

    def load_writing_context(project_id, owner_id: str):
        with app.state.session_factory() as session:
            project = project_or_404(session, project_id, owner_id)
            project_data = ProjectInput.model_validate({key: getattr(project, key) for key in ProjectInput.model_fields}).model_dump()
            formats = list(session.scalars(select(ArticleFormat).where(ArticleFormat.project_id == project_id, ArticleFormat.is_active.is_(True))))
            if not formats:
                raise HTTPException(422, "Hãy thêm ít nhất một dạng bài đang bật vào dự án trước khi viết.")
            format_data = []
            for item in formats:
                data = FormatInput.model_validate({key: getattr(item, key) for key in FormatInput.model_fields}).model_dump()
                data["id"] = str(item.id)
                format_data.append(data)
            return project_data, format_data

    def save_post(payload, owner_id: str, pages, result, extraction_warnings):
        with app.state.session_factory() as session:
            project_or_404(session, payload.project_id, owner_id)
            chosen_id = UUID(result.format["id"])
            chosen_format = session.get(ArticleFormat, chosen_id)
            if not chosen_format or chosen_format.project_id != payload.project_id:
                chosen_id = None
            item = GeneratedPost(
                project_id=payload.project_id, format_id=chosen_id,
                source_type=payload.source_type, source_url=payload.source_url if payload.source_type == "url" else None,
                source_text=payload.source_text if payload.source_type == "facebook_paste" else pages[0].text,
                source_title=pages[0].title, sources=[page.to_dict() for page in pages],
                facts={"items": [fact.model_dump() for fact in result.analysis.facts]},
                selected_format_name=result.format["name"], selection_reason=result.analysis.reason,
                confidence=result.analysis.confidence, format_snapshot=result.format,
                generated_content=result.content, original_content=result.content,
                warnings=list(dict.fromkeys(extraction_warnings + result.warnings)),
                additional_instructions=payload.additional_instructions, model=settings.ai_model,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            )
            session.add(item)
            session.commit()
            return PostOut.model_validate(item)

    @api.post("/generate", response_model=PostOut, status_code=201)
    async def generate(payload: GenerateInput, user: AuthUser = Depends(require_auth)):
        if not settings.ai_api_key.get_secret_value():
            logger.warning("Generation failed code=AI_KEY_MISSING")
            key_name = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}.get(settings.ai_provider, "OPENAI_API_KEY")
            return JSONResponse({"detail": f"Chưa cấu hình {key_name} trên máy chủ.", "code": "AI_KEY_MISSING"}, status_code=503)
        project_data, formats = await run_in_threadpool(load_writing_context, payload.project_id, user.owner_id)
        if app.state.generation_slots.locked():
            raise HTTPException(429, "Đang có nhiều bài được tạo. Hãy đợi một chút rồi thử lại.", headers={"Retry-After": "15"})
        app.state.limiter.check(f"generation:{user.owner_id}", settings.generate_requests_per_hour, 3600)
        await app.state.generation_slots.acquire()
        try:
            # Hard overall deadline; failed/refused calls do not create history records.
            async with asyncio.timeout(330):
                if payload.source_type == "url":
                    pages, warnings = await extract_website(payload.source_url, payload.follow_related)
                else:
                    pages, warnings = pasted_source(payload.source_text), []
                result = await app.state.writer.write(project_data, formats, pages, payload.additional_instructions)
                return await run_in_threadpool(save_post, payload, user.owner_id, pages, result, warnings)
        except ExtractionError as error:
            raise HTTPException(422, str(error)) from None
        except WritingError as error:
            # Do not log upstream bodies, headers, prompts, keys or base URL paths.
            logger.warning(
                "Generation failed code=%s upstream_status=%s api_mode=%s response_format=%s",
                error.code, error.upstream_status, settings.ai_api_mode, settings.ai_response_format,
            )
            return JSONResponse(
                {"detail": str(error), "code": error.code, "upstream_status": error.upstream_status},
                status_code=error.status_code,
            )
        except TimeoutError:
            raise HTTPException(504, "Quá thời gian tạo bài. Hãy thử nguồn ngắn hơn hoặc kiểm tra lịch sử trước khi thử lại.") from None
        finally:
            app.state.generation_slots.release()

    app.include_router(api)
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    return app


app = create_app()
