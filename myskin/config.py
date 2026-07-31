from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myskin.settings_loader import cfg_bool, cfg_get, cfg_optional, cfg_path, ensure_config_loaded, secrets


@dataclass(frozen=True)
class OidcSettings:
    issuer_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool
    post_login_redirect: str
    allowed_group: str | None
    oidc: OidcSettings | None


class Settings:
    def __init__(self) -> None:
        ensure_config_loaded()
        self.data_dir: Path = cfg_path("api.data_dir", "./data")
        self.host: str = str(cfg_get("api.host", default="0.0.0.0"))
        self.port: int = int(cfg_get("api.port", default=8080))
        public_base_url = cfg_get("api.public_base_url", default=None)
        self.public_base_url: str = str(public_base_url).strip() if public_base_url else ""

        self.session_secret: str = str(
            cfg_get("server.session_secret", default="change-me-in-production")
        )
        self.session_https_only: bool = cfg_bool("server.session_https_only", False)

        auth_enabled = cfg_bool("auth.enabled", False)
        post_login_redirect = str(
            cfg_get("auth.post_login_redirect", default="/admin")
        )
        allowed_raw = cfg_optional("auth.allowed_group")
        allowed_group = (
            str(allowed_raw).strip()
            if allowed_raw is not None and str(allowed_raw).strip()
            else None
        )

        oidc: OidcSettings | None = None
        if auth_enabled:
            scopes = cfg_get("auth.oidc.scopes", default=["openid", "profile", "email"])
            if isinstance(scopes, str):
                scopes = [s.strip() for s in scopes.split() if s.strip()]
            oidc = OidcSettings(
                issuer_url=str(cfg_get("auth.oidc.issuer_url", required=True)).rstrip("/"),
                client_id=str(cfg_get("auth.oidc.client_id", required=True)),
                client_secret=str(cfg_get("auth.oidc.client_secret", required=True)),
                redirect_uri=str(cfg_get("auth.oidc.redirect_uri", required=True)),
                scopes=tuple(scopes),
            )

        self.auth = AuthSettings(
            enabled=auth_enabled,
            post_login_redirect=post_login_redirect,
            allowed_group=allowed_group,
            oidc=oidc,
        )

    @property
    def api_token(self) -> str:
        return secrets().api_token

    @property
    def bearer_enabled(self) -> bool:
        return bool(self.api_token.strip())

    @property
    def oidc_enabled(self) -> bool:
        return self.auth.enabled and self.auth.oidc is not None

    @property
    def auth_required(self) -> bool:
        return self.oidc_enabled or self.bearer_enabled

    @property
    def auth_enabled(self) -> bool:
        """True when any auth mechanism is active (Bearer and/or OIDC)."""
        return self.auth_required


settings = Settings()
