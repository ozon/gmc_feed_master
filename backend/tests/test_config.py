from app.config import Settings
from pydantic import ValidationError


def test_session_defaults(monkeypatch):
    for key in ("SESSION_IDLE_MINUTES", "SESSION_ABSOLUTE_HOURS"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None, session_secret="test-secret")
    assert settings.session_idle_minutes == 30
    assert settings.session_absolute_hours == 12


def test_settings_require_credentials(monkeypatch):
    for key in ("SESSION_SECRET", "INITIAL_USERNAME", "INITIAL_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    try:
        Settings(_env_file=None)
    except ValidationError as error:
        assert {item["loc"][0] for item in error.errors()} >= {
            "session_secret",
            "initial_username",
            "initial_password",
        }
    else:
        raise AssertionError("Settings should require session credentials")


def test_settings_reject_non_positive_durations():
    for field in ("session_idle_minutes", "session_absolute_hours"):
        try:
            Settings(
                _env_file=None,
                session_secret="test-secret",
                initial_username="test-user",
                initial_password="test-password",
                **{field: 0},
            )
        except ValidationError:
            pass
        else:
            raise AssertionError(f"{field} should be positive")
