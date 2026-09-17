from app import main as main_module
from app.config import Settings


def test_create_app_resolves_settings_before_configure_logging(monkeypatch):
    settings = Settings(
        _env_file=None,
        session_secret="s",
        initial_username="u",
        initial_password="p",
        log_format="console",
        log_level="DEBUG",
    )
    calls: list[Settings | None] = []
    monkeypatch.setattr(main_module, "_configured_settings", lambda: settings)
    monkeypatch.setattr(main_module, "configure_logging", calls.append)
    monkeypatch.setattr(main_module, "create_engine", lambda *_a, **_k: None)
    monkeypatch.setattr(main_module, "create_session_factory", lambda *_a, **_k: None)

    main_module.create_app()

    assert calls == [settings]
