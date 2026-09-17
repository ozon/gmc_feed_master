from app.config import Settings


def test_logging_settings_defaults():
    settings = Settings(
        _env_file=None,
        session_secret="s",
        initial_username="u",
        initial_password="p",
    )
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    assert settings.event_log_retention_days == 180


def test_logging_settings_env_override(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_FORMAT", "console")
    monkeypatch.setenv("EVENT_LOG_RETENTION_DAYS", "30")
    settings = Settings(
        _env_file=None,
        session_secret="s",
        initial_username="u",
        initial_password="p",
    )
    assert settings.log_level == "DEBUG"
    assert settings.log_format == "console"
    assert settings.event_log_retention_days == 30
