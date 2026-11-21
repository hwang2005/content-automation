import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "content_studio_session"
SESSION_SECONDS = 12 * 60 * 60


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


def signer(request: Request):
    settings = request.app.state.settings
    secret = settings.session_secret.get_secret_value() or request.app.state.local_session_secret
    # Rotating the workspace password invalidates existing sessions.
    return URLSafeTimedSerializer(secret, salt="workspace:" + settings.app_password.get_secret_value())


def authenticated(request: Request) -> bool:
    settings = request.app.state.settings
    if not settings.auth_ready:
        return False
    if not settings.app_password.get_secret_value() and not settings.production:
        return True
    try:
        payload = signer(request).loads(request.cookies.get(COOKIE_NAME, ""), max_age=SESSION_SECONDS)
        return payload.get("workspace") == "main"
    except (BadSignature, SignatureExpired):
        return False


def require_auth(request: Request):
    if not request.app.state.settings.auth_ready:
        raise HTTPException(503, "Cần cấu hình APP_PASSWORD (12+ ký tự) và SESSION_SECRET (32+ ký tự).")
    if not authenticated(request):
        raise HTTPException(401, "Vui lòng đăng nhập để tiếp tục.")


def check_password(request: Request, password: str) -> bool:
    expected = request.app.state.settings.app_password.get_secret_value()
    return bool(expected) and secrets.compare_digest(password.encode(), expected.encode())
