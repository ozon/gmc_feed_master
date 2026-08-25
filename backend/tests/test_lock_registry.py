import asyncio

from app.pipeline import LockRegistry


def test_get_returns_same_lock_per_id():
    registry = LockRegistry()
    lock_a = registry.get(1)
    lock_b = registry.get(1)
    lock_c = registry.get(2)
    assert isinstance(lock_a, asyncio.Lock)
    assert lock_a is lock_b
    assert lock_a is not lock_c


def test_is_locked_lifecycle():
    async def scenario():
        registry = LockRegistry()
        assert registry.is_locked(1) is False
        lock = registry.get(1)
        await lock.acquire()
        try:
            assert registry.is_locked(1) is True
            assert registry.is_locked(2) is False
        finally:
            lock.release()
        assert registry.is_locked(1) is False

    asyncio.run(scenario())


def test_discard_removes_entry():
    registry = LockRegistry()
    original = registry.get(1)
    registry.discard(1)
    assert registry.get(1) is not original
    assert registry.is_locked(1) is False


def test_discard_unknown_id_is_noop():
    registry = LockRegistry()
    registry.discard(999)
    assert registry.is_locked(999) is False
