from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings


class SessionManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._serializer = URLSafeSerializer(settings.secret_key, salt="ffsubsync-web")

    def authenticate(self, password: str) -> bool:
        return password == self._settings.app_password

    def is_authenticated(self, request: Request) -> bool:
        raw_cookie = request.cookies.get(self._settings.session_cookie_name)
        if not raw_cookie:
            return False
        try:
            payload = self._serializer.loads(raw_cookie)
        except BadSignature:
            return False
        return payload.get("authenticated") is True

    def set_session(self, response: Response) -> None:
        token = self._serializer.dumps({"authenticated": True})
        response.set_cookie(
            key=self._settings.session_cookie_name,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
        )

    def clear_session(self, response: Response) -> None:
        response.delete_cookie(self._settings.session_cookie_name)
