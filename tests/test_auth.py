from lightbeacon.auth import SessionManager, hash_password, verify_password


def test_password_hash_and_verify() -> None:
    encoded = hash_password("a-correct-password")
    assert verify_password("a-correct-password", encoded)
    assert not verify_password("wrong-password", encoded)
    assert "a-correct-password" not in encoded


def test_signed_session_rejects_tampering() -> None:
    manager = SessionManager(bytes(range(32)))
    token = manager.issue()
    assert manager.verify(token)
    assert not manager.verify(token[:-1] + ("A" if token[-1] != "A" else "B"))

