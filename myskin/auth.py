"""Instance auth: Keycloak OIDC (session) and optional Bearer API token."""

from __future__ import annotations

import logging
from typing import Any

from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import JSONResponse, RedirectResponse

from myskin.config import settings

logger = logging.getLogger(__name__)

oauth = OAuth()
router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


def configure_oauth() -> None:
    if not settings.oidc_enabled or settings.auth.oidc is None:
        return
    oidc = settings.auth.oidc
    issuer = oidc.issuer_url.rstrip("/")
    oauth.register(
        name="keycloak",
        server_metadata_url=f"{issuer}/.well-known/openid-configuration",
        client_id=oidc.client_id,
        client_secret=oidc.client_secret,
        client_kwargs={"scope": " ".join(oidc.scopes)},
    )


def _normalize_groups(userinfo: dict[str, Any]) -> set[str]:
    groups: set[str] = set()
    raw = userinfo.get("groups")
    if isinstance(raw, list):
        groups.update(str(item) for item in raw if item)

    realm_access = userinfo.get("realm_access")
    if isinstance(realm_access, dict):
        roles = realm_access.get("roles")
        if isinstance(roles, list):
            groups.update(str(item) for item in roles if item)

    return groups


def _user_in_allowed_group(userinfo: dict[str, Any]) -> bool:
    allowed = settings.auth.allowed_group
    if not allowed:
        return True
    groups = _normalize_groups(userinfo)
    return bool(groups.intersection({allowed, f"/{allowed}"}))


def get_current_user(request: Request) -> dict[str, Any] | None:
    if not settings.oidc_enabled:
        return None
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def _bearer_ok(credentials: HTTPAuthorizationCredentials | None) -> bool:
    if not settings.bearer_enabled:
        return False
    if credentials is None or credentials.scheme.lower() != "bearer":
        return False
    return credentials.credentials == settings.api_token


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Accept a valid OIDC session and/or Bearer API token when configured."""
    if not settings.auth_required:
        return

    if _bearer_ok(credentials):
        return

    if settings.oidc_enabled and get_current_user(request) is not None:
        return

    if settings.oidc_enabled and not settings.bearer_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Bearer token required" if settings.bearer_enabled else "Authentication required",
        headers={"WWW-Authenticate": "Bearer"} if settings.bearer_enabled else None,
    )


# Back-compat alias for imports that still say require_token.
require_token = require_auth


@router.get("/config")
def auth_config() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": settings.oidc_enabled,
        "bearer_enabled": settings.bearer_enabled,
    }
    if settings.oidc_enabled:
        payload["login_url"] = "/auth/login"
    return payload


@router.get("/login")
async def login(request: Request):
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="Authentication is disabled")
    oidc = settings.auth.oidc
    assert oidc is not None
    return await oauth.keycloak.authorize_redirect(request, oidc.redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="Authentication is disabled")

    try:
        token = await oauth.keycloak.authorize_access_token(request)
    except MismatchingStateError:
        logger.warning("OAuth callback with stale or missing session state; restarting login")
        request.session.clear()
        return RedirectResponse(url="/auth/login", status_code=302)
    except OAuthError as exc:
        logger.warning("OAuth callback failed: %s", exc)
        request.session.clear()
        return RedirectResponse(url="/auth/login", status_code=302)

    userinfo = token.get("userinfo")
    if userinfo is None:
        userinfo = await oauth.keycloak.userinfo(token=token)

    if not _user_in_allowed_group(userinfo):
        request.session.clear()
        return JSONResponse(
            status_code=403,
            content={
                "error": "Access denied",
                "detail": (
                    f"Membership in group '{settings.auth.allowed_group}' is required"
                ),
            },
        )

    session_user: dict[str, Any] = {
        "sub": userinfo.get("sub"),
        "email": userinfo.get("email"),
        "name": userinfo.get("name") or userinfo.get("preferred_username"),
        "preferred_username": userinfo.get("preferred_username"),
    }
    if settings.auth.allowed_group:
        session_user["groups"] = sorted(_normalize_groups(userinfo))
    request.session["user"] = session_user
    return RedirectResponse(url=settings.auth.post_login_redirect)


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    if not settings.oidc_enabled:
        return {"authenticated": False, "user": None}

    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"authenticated": True, "user": user}


@router.post("/logout")
def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}
