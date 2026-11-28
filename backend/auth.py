import base64
import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import aiohttp
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.config import Settings

COOKIE_NAME = "content_studio_session"
OAUTH_COOKIE_NAME = "content_studio_oauth"
SESSION_SECONDS = 12 * 60 * 60
OAUTH_STATE_SECONDS = 10 * 60


@dataclass(frozen=True)
class AuthUser:
    owner_id: str
    auth_method: str
    email: str | None = None
    name: str | None = None


class OAuthExchangeError(Exception):
    """Safe OAuth token/user exchange failure without exposing upstream secrets."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class RateLimiter:
    """Bounded, process-local limiter. Deploy one worker; use Redis before scaling."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str, limit: int, seconds: int):
        now = time.monotonic()
        with self.lock:
            # Also discard expired clients to keep anonymous login attempts bounded.
            for old in list(self.hits):
                if not self.hits[old] or self.hits[old][-1] <= now - 3600:
                    del self.hits[old]
            if len(self.hits) >= 10000 and key not in self.hits:
                raise HTTPException(429, "Máy chủ đang bận. Vui lòng thử lại sau.")
            queue = self.hits[key]
            while queue and queue[0] <= now - seconds:
                queue.popleft()
            if len(queue) >= limit:
                retry = max(1, int(seconds - (now - queue[0])) + 1)
                raise HTTPException(
                    429, "Đã đạt giới hạn yêu cầu. Vui lòng thử lại sau.",
                    headers={"Retry-After": str(retry)},
                )
            queue.append(now)


def _session_secret(request: Request) -> str:
    settings = request.app.state.settings
    return settings.session_secret.get_secret_value() or request.app.state.local_session_secret


def password_fingerprint(settings: Settings) -> str:
    return hashlib.sha256(settings.app_password.get_secret_value().encode("utf-8")).hexdigest()[:16]


def signer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_session_secret(request), salt="content-studio-session:v1")


def oauth_flow_signer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_session_secret(request), salt="content-studio-oauth-flow:v1")


def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def create_password_session_token(request: Request) -> str:
    return signer(request).dumps({
        "auth_method": "password",
        "pw_ver": password_fingerprint(request.app.state.settings),
        "nonce": secrets.token_hex(16),
    })


def create_google_session_token(request: Request, user_id: str, email: str, name: str) -> str:
    return signer(request).dumps({
        "auth_method": "google",
        "owner_id": f"supabase:{user_id}",
        "email": email,
        "name": name,
        "nonce": secrets.token_hex(16),
    })


def current_user(request: Request) -> AuthUser | None:
    settings = request.app.state.settings
    if not settings.auth_ready:
        return None
    raw_cookie = request.cookies.get(COOKIE_NAME, "")
    if raw_cookie:
        try:
            payload = signer(request).loads(raw_cookie, max_age=SESSION_SECONDS)
            method = payload.get("auth_method")
            if method == "google":
                owner_id = payload.get("owner_id")
                email = str(payload.get("email") or "").strip()
                if (
                    settings.google_oauth_enabled
                    and isinstance(owner_id, str)
                    and owner_id.startswith("supabase:")
                    and len(owner_id) > len("supabase:")
                    and email
                    and (not settings.allowed_email_set or email.lower() in settings.allowed_email_set)
                ):
                    name = str(payload.get("name") or email).strip() or email
                    return AuthUser(owner_id=owner_id, auth_method="google", email=email, name=name)
            elif method == "password":
                if settings.password_auth_enabled and secrets.compare_digest(
                    str(payload.get("pw_ver", "")), password_fingerprint(settings)
                ):
                    return AuthUser(owner_id="workspace", auth_method="password", name="Workspace")
        except (BadSignature, SignatureExpired):
            pass
    if not settings.login_required:
        return AuthUser(owner_id="workspace", auth_method="local", name="Local workspace")
    return None


def authenticated(request: Request) -> bool:
    return current_user(request) is not None


def require_auth(request: Request) -> AuthUser:
    if not request.app.state.settings.auth_ready:
        raise HTTPException(
            503,
            "Cần cấu hình SESSION_SECRET (32+ ký tự) cùng APP_PASSWORD (12+ ký tự) hoặc Supabase Google OAuth.",
        )
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Vui lòng đăng nhập để tiếp tục.")
    return user


def check_password(request: Request, password: str) -> bool:
    expected = request.app.state.settings.app_password.get_secret_value()
    return bool(expected) and secrets.compare_digest(password.encode(), expected.encode())


async def exchange_supabase_pkce(settings: Settings, auth_code: str, code_verifier: str) -> dict:
    """Exchange a Supabase PKCE authorization code for verified user identity."""
    anon_key = settings.supabase_anon_key.get_secret_value()
    if not settings.supabase_url or not anon_key:
        raise OAuthExchangeError("oauth_not_configured")

    base_headers = {"apikey": anon_key, "Accept": "application/json"}
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.post(
                f"{settings.supabase_url}/auth/v1/token?grant_type=pkce",
                headers={**base_headers, "Content-Type": "application/json"},
                json={"auth_code": auth_code, "code_verifier": code_verifier},
            ) as response:
                if response.status != 200:
                    raise OAuthExchangeError("oauth_exchange_failed")
                data = await response.json()

            user = data.get("user") if isinstance(data, dict) else None
            if not isinstance(user, dict):
                access_token = data.get("access_token") if isinstance(data, dict) else None
                if not isinstance(access_token, str) or not access_token:
                    raise OAuthExchangeError("oauth_exchange_failed")
                async with http.get(
                    f"{settings.supabase_url}/auth/v1/user",
                    headers={**base_headers, "Authorization": f"Bearer {access_token}"},
                ) as user_response:
                    if user_response.status != 200:
                        raise OAuthExchangeError("oauth_exchange_failed")
                    user = await user_response.json()
    except OAuthExchangeError:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError):
        raise OAuthExchangeError("oauth_exchange_failed") from None

    if not isinstance(user, dict):
        raise OAuthExchangeError("oauth_exchange_failed")

    user_id = str(user.get("id") or "").strip()
    email = str(user.get("email") or "").strip()
    if not user_id or not email:
        raise OAuthExchangeError("oauth_exchange_failed")

    metadata = user.get("user_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    name = str(metadata.get("full_name") or metadata.get("name") or email.split("@")[0]).strip()[:120]
    email_verified = bool(
        user.get("email_confirmed_at") or user.get("confirmed_at") or metadata.get("email_verified")
    )
    return {
        "id": user_id,
        "email": email,
        "name": name or email,
        "email_verified": email_verified,
    }
