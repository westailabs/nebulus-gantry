import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("GANTRY_DATA_DIR", "data"))


def _get_database_url() -> str:
    return os.getenv("DATABASE_URL", f"sqlite:///./{DATA_DIR}/gantry.db")


def _get_secret_key() -> str:
    """Return the secret key for session signing.

    Priority: SECRET_KEY env var > secret_key_manager (file-backed).
    Delegates to secret_key_manager for generation, persistence, and
    atomic writes with proper file permissions (0o600).

    Note: sessions are random DB-stored tokens, so this key is currently
    reserved for future signing; nothing signs with it yet.
    """
    env_key = (os.getenv("SECRET_KEY") or "").strip()
    if env_key:
        if len(env_key) < 32:
            logger.warning("SECRET_KEY is shorter than 32 characters; use a random 32+ character value.")
        return env_key

    from backend.services.secret_key_manager import get_secret_key

    return get_secret_key(DATA_DIR)


def _get_session_expire_hours() -> int:
    return int(os.getenv("SESSION_EXPIRE_HOURS", "24"))


def _get_overlord_routing_enabled() -> bool:
    return os.getenv("OVERLORD_ROUTING_ENABLED", "true").lower() in ("true", "1", "yes")


def _get_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:5173", "http://localhost:3000"]


def _get_bind_host() -> str:
    return os.getenv("BIND_HOST", "127.0.0.1")


def _get_https_enabled() -> bool:
    return os.getenv("HTTPS_ENABLED", "false").lower() in ("true", "1", "yes")


def _get_atom_base_url() -> str:
    return os.getenv("ATOM_BASE_URL", "http://localhost:8010")


def _get_demo_mode() -> bool:
    """CPA demo profile switch (GANTRY_DEMO_MODE). Default off; see docs/cpa-demo-mode.md."""
    return os.getenv("GANTRY_DEMO_MODE", "false").strip().lower() in ("true", "1", "yes")


def _get_demo_firm_name() -> str:
    """Fictional firm name shown in demo mode (GANTRY_DEMO_FIRM_NAME). Empty means none."""
    return (os.getenv("GANTRY_DEMO_FIRM_NAME") or "").strip()


@dataclass
class Settings:
    database_url: str = field(default_factory=_get_database_url)
    secret_key: str = field(default_factory=_get_secret_key, repr=False)
    session_expire_hours: int = field(default_factory=_get_session_expire_hours)
    overlord_routing_enabled: bool = field(default_factory=_get_overlord_routing_enabled)
    cors_origins: list[str] = field(default_factory=_get_cors_origins)
    bind_host: str = field(default_factory=_get_bind_host)
    https_enabled: bool = field(default_factory=_get_https_enabled)
    atom_base_url: str = field(default_factory=_get_atom_base_url)
    demo_mode: bool = field(default_factory=_get_demo_mode)
    demo_firm_name: str = field(default_factory=_get_demo_firm_name)


settings = Settings()
