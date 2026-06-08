"""Encrypted application settings — API keys and AI provider configuration.

Secrets are encrypted at rest with Fernet (AES-128-CBC + HMAC). The encryption
key lives in a 0600 file next to the database (`data/.vendorfair.key`), so the
database file alone cannot reveal stored API keys.
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

import config
from database.db import session_scope
from database.models import AppSetting

PROVIDERS = {
    "anthropic": "Anthropic Claude",
    "gemini": "Google Gemini",
    "openai": "OpenAI ChatGPT",
}

DEFAULT_MODELS = {
    "anthropic": config.CLAUDE_MODEL,
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-5",
}

# Environment-variable fallbacks (.env) when no key is stored in the database
ENV_KEY_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}

_KEY_FILE = Path(config.DB_PATH).parent / ".vendorfair.key"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if _KEY_FILE.exists():
            key = _KEY_FILE.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            _KEY_FILE.touch(mode=0o600, exist_ok=True)
            _KEY_FILE.write_bytes(key)
            _KEY_FILE.chmod(0o600)
        _fernet = Fernet(key)
    return _fernet


# ---------------------------------------------------------------- raw settings
def set_setting(key: str, value: str, encrypted: bool = False) -> None:
    stored = _get_fernet().encrypt(value.encode()).decode() if encrypted else value
    with session_scope() as session:
        setting = session.query(AppSetting).filter(AppSetting.key == key).first()
        if setting is None:
            session.add(AppSetting(key=key, value=stored, is_encrypted=encrypted))
        else:
            setting.value = stored
            setting.is_encrypted = encrypted


def get_setting(key: str) -> str | None:
    with session_scope() as session:
        setting = session.query(AppSetting).filter(AppSetting.key == key).first()
        if setting is None or not setting.value:
            return None
        if not setting.is_encrypted:
            return setting.value
        try:
            return _get_fernet().decrypt(setting.value.encode()).decode()
        except InvalidToken:
            # Key file was replaced/lost — treat the secret as unreadable
            return None


def delete_setting(key: str) -> None:
    with session_scope() as session:
        session.query(AppSetting).filter(AppSetting.key == key).delete()


# ---------------------------------------------------------------- API keys
def set_api_key(provider: str, api_key: str) -> None:
    _validate_provider(provider)
    set_setting(f"api_key_{provider}", api_key.strip(), encrypted=True)


def clear_api_key(provider: str) -> None:
    _validate_provider(provider)
    delete_setting(f"api_key_{provider}")


def get_api_key(provider: str) -> str:
    """Effective API key: encrypted DB value first, then .env fallback."""
    _validate_provider(provider)
    stored = get_setting(f"api_key_{provider}")
    if stored:
        return stored
    return os.getenv(ENV_KEY_VARS[provider], "")


def api_key_hint(provider: str) -> str:
    """Masked description of where the key comes from — never the key itself."""
    _validate_provider(provider)
    stored = get_setting(f"api_key_{provider}")
    if stored:
        return f"••••{stored[-4:]} (stored encrypted)"
    if os.getenv(ENV_KEY_VARS[provider], ""):
        return f"set via {ENV_KEY_VARS[provider]} in .env"
    return "not set"


# ---------------------------------------------------------------- AI provider
def get_ai_provider() -> str:
    provider = get_setting("ai_provider")
    return provider if provider in PROVIDERS else "anthropic"


def set_ai_provider(provider: str) -> None:
    _validate_provider(provider)
    set_setting("ai_provider", provider)


def get_ai_model(provider: str) -> str:
    _validate_provider(provider)
    return get_setting(f"ai_model_{provider}") or DEFAULT_MODELS[provider]


def set_ai_model(provider: str, model: str) -> None:
    _validate_provider(provider)
    set_setting(f"ai_model_{provider}", model.strip())


def _validate_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown AI provider: {provider}")


# ---------------------------------------------------------------- UI theme
UI_THEMES = ("dark", "light")


def get_ui_theme() -> str:
    """Persisted UI theme; defaults to dark."""
    value = get_setting("ui_theme")
    return value if value in UI_THEMES else "dark"


def set_ui_theme(theme: str) -> None:
    if theme not in UI_THEMES:
        raise ValueError(f"Unknown UI theme: {theme}")
    set_setting("ui_theme", theme)
