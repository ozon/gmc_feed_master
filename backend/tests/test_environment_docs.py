from pathlib import Path


def test_env_example_documents_required_settings():
    root = Path(__file__).resolve().parents[2]
    text = (root / ".env.example").read_text()

    for key in (
        "DATABASE_URL",
        "SESSION_SECRET",
        "INITIAL_USERNAME",
        "INITIAL_PASSWORD",
        "SESSION_IDLE_MINUTES",
        "SESSION_ABSOLUTE_HOURS",
    ):
        assert f"{key}=" in text


def test_compose_defines_only_healthy_postgres_service():
    root = Path(__file__).resolve().parents[2]
    text = (root / "docker-compose.yml").read_text()

    services = text.split("services:", 1)[1].split("\nvolumes:", 1)[0]
    service_names = [
        line.strip()[:-1]
        for line in services.splitlines()
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":")
    ]

    assert service_names == ["postgres"]
    assert "healthcheck:" in services
    assert "pg_isready" in services
