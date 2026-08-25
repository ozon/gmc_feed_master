from __future__ import annotations

import asyncio


class LockRegistry:
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    def get(self, feed_source_id: int) -> asyncio.Lock:
        lock = self._locks.get(feed_source_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[feed_source_id] = lock
        return lock

    def is_locked(self, feed_source_id: int) -> bool:
        lock = self._locks.get(feed_source_id)
        return lock is not None and lock.locked()

    def discard(self, feed_source_id: int) -> None:
        self._locks.pop(feed_source_id, None)
