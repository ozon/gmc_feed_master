from app.security.passwords import hash_password, verify_password


def test_password_hash_is_argon2id_and_not_plaintext():
    password_hash = hash_password("correct")

    assert password_hash.startswith("$argon2id$")
    assert password_hash != "correct"
    assert verify_password("correct", password_hash)
    assert not verify_password("wrong", password_hash)


def test_password_verification_rejects_invalid_hashes():
    assert not verify_password("correct", "not-a-password-hash")
