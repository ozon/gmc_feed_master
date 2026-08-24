from app.auth import SESSION_COOKIE_NAME


VALID_CREDENTIALS = {"username": "operator", "password": "correct"}


def test_login_sets_secure_cookie_and_returns_operator(client):
    response = client.post("/auth/login", json=VALID_CREDENTIALS)

    assert response.status_code == 200
    assert response.json() == {"username": "operator"}
    cookie = response.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE_NAME.lower()}=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=43200" in cookie


def test_wrong_credentials_are_rejected_without_disclosing_field(client):
    response = client.post(
        "/auth/login", json={"username": "operator", "password": "wrong"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_unknown_username_has_same_generic_credential_error(client):
    response = client.post(
        "/auth/login", json={"username": "unknown", "password": "wrong"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_me_returns_current_operator_without_renewing_idle(client, clock):
    assert client.post("/auth/login", json=VALID_CREDENTIALS).status_code == 200

    clock.advance(minutes=29)
    assert client.get("/auth/me").json() == {"username": "operator"}
    clock.advance(minutes=2)
    assert client.get("/auth/me").status_code == 401


def test_interaction_renews_idle_expiry(client, clock):
    assert client.post("/auth/login", json=VALID_CREDENTIALS).status_code == 200
    clock.advance(minutes=29)

    assert client.post("/auth/interaction").status_code == 200
    clock.advance(minutes=29)
    assert client.get("/auth/me").status_code == 200


def test_interaction_cannot_extend_absolute_expiry(client, clock):
    assert client.post("/auth/login", json=VALID_CREDENTIALS).status_code == 200
    clock.advance(hours=12, seconds=1)

    assert client.post("/auth/interaction").status_code == 401


def test_missing_cookie_is_rejected(client):
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/interaction").status_code == 401
    assert client.post("/auth/logout").status_code == 401


def test_logout_invalidates_session_and_clears_matching_cookie(client):
    assert client.post("/auth/login", json=VALID_CREDENTIALS).status_code == 200

    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    cookie = response.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE_NAME.lower()}=" in cookie
    assert "max-age=0" in cookie
    assert "expires=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert client.get("/auth/me").status_code == 401


def test_login_replaces_existing_session_cookie(client):
    first = client.post("/auth/login", json=VALID_CREDENTIALS)
    first_token = client.cookies[SESSION_COOKIE_NAME]
    second = client.post("/auth/login", json=VALID_CREDENTIALS)

    assert second.status_code == 200
    assert client.cookies[SESSION_COOKIE_NAME] != first_token
