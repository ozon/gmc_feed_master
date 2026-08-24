from pathlib import Path
import json
import subprocess


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
    result = subprocess.run(
        ["docker", "compose", "-f", str(root / "docker-compose.yml"), "config", "--format", "json"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    config = json.loads(result.stdout)

    assert list(config["services"]) == ["postgres"]
    assert "healthcheck" in config["services"]["postgres"]
