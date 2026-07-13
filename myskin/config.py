from pathlib import Path

from myskin.settings_loader import cfg_get, cfg_path, ensure_config_loaded, secrets


class Settings:
    def __init__(self) -> None:
        ensure_config_loaded()
        self.data_dir: Path = cfg_path("api.data_dir", "./data")
        self.host: str = str(cfg_get("api.host", default="0.0.0.0"))
        self.port: int = int(cfg_get("api.port", default=8080))
        public_base_url = cfg_get("api.public_base_url", default=None)
        self.public_base_url: str = str(public_base_url).strip() if public_base_url else ""

    @property
    def api_token(self) -> str:
        return secrets().api_token

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_token.strip())


settings = Settings()
