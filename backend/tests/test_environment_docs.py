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


def test_frontend_proxy_and_ci_startup_are_documented():
    root = Path(__file__).resolve().parents[2]
    vite_config = (root / "frontend" / "vite.config.ts").read_text()
    assert "'/auth'" in vite_config
    assert "'/health'" in vite_config
    assert "127.0.0.1:8000" in vite_config
    assert "loadEnv(mode, rootDir, '')" in vite_config
    assert "VITE_HTTPS_CERT" in vite_config
    assert "VITE_HTTPS_KEY" in vite_config
    assert "must be set together" in vite_config
    assert "https:" in vite_config

    workflow = (root / ".github" / "workflows" / "ci.yml").read_text()
    assert "docker compose up -d --wait postgres" in workflow
    assert "docker compose down --volumes" in workflow


def test_readme_documents_local_https_setup():
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text()

    assert "openssl req -x509" in readme
    assert "VITE_HTTPS_CERT" in readme
    assert "VITE_HTTPS_KEY" in readme
    assert "https://localhost:5173" in readme
    assert "http://127.0.0.1:8000" in readme
