from datetime import timedelta

from app.session_store import InMemorySessionStore


def test_create_and_validate_returns_user_id(store, clock):
    token = store.create("operator", clock.now())
    assert store.validate(token, clock.now(), renew_idle=False) == "operator"


def test_read_validation_does_not_renew_idle_expiry(store, clock):
    token = store.create("operator", clock.now())
    clock.advance(minutes=29)
    assert store.validate(token, clock.now(), renew_idle=False) == "operator"
    clock.advance(minutes=2)
    assert store.validate(token, clock.now(), renew_idle=False) is None


def test_explicit_interaction_renews_idle_but_not_absolute(store, clock):
    token = store.create("operator", clock.now())
    absolute = clock.now() + timedelta(hours=12)
    clock.advance(minutes=29)
    assert store.validate(token, clock.now(), renew_idle=True) == "operator"
    clock.advance(minutes=29)
    assert store.validate(token, clock.now(), renew_idle=False) == "operator"
    clock.set(absolute + timedelta(seconds=1))
    assert store.validate(token, clock.now(), renew_idle=True) is None


def test_invalidate_rejects_existing_token(store, clock):
    token = store.create("operator", clock.now())
    store.invalidate(token)
    assert store.validate(token, clock.now(), renew_idle=False) is None


def test_restart_invalidates_tokens(store, clock):
    token = store.create("operator", clock.now())
    restarted = InMemorySessionStore(
        idle=timedelta(minutes=30), absolute=timedelta(hours=12), secret="test-secret"
    )
    assert restarted.validate(token, clock.now(), renew_idle=False) is None


def test_malformed_and_tampered_tokens_are_rejected(store, clock):
    token = store.create("operator", clock.now())
    for invalid in ("", "not-a-token", token + "x", token.replace(".", "", 1)):
        assert store.validate(invalid, clock.now(), renew_idle=False) is None


def test_idle_deadline_is_capped_by_absolute_deadline(store, clock):
    capped_store = InMemorySessionStore(
        idle=timedelta(hours=2), absolute=timedelta(hours=3), secret="test-secret"
    )
    token = capped_store.create("operator", clock.now())
    clock.advance(hours=1, minutes=59)
    assert capped_store.validate(token, clock.now(), renew_idle=True) == "operator"
    clock.advance(hours=1, minutes=1, seconds=1)
    assert capped_store.validate(token, clock.now(), renew_idle=False) is None
