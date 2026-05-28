"""
Shared in-process event bus for fleet-wide SSE.
Imported by both app.py (route) and sdk_engine.py (emitters) to avoid circular deps.

v17: per-subscriber project-scope filtering. Each subscriber carries the
authenticated user_id; events that carry a `project_id` are only delivered to
subscribers whose bound-project set includes it (admins and the unauthenticated
system stream see everything). The bound-project set is cached per subscriber
with a 5s TTL so an admin grant/revoke propagates without forcing a reconnect.
"""
import asyncio
import time

_subscribers: list["_Subscriber"] = []

_CACHE_TTL_SECONDS = 5.0


class _Subscriber:
    """SSE subscriber with project-scope filtering. Exposes the slice of the
    asyncio.Queue interface the /api/events handler uses (`get()`), so callers
    only need to pass their user_id at subscribe time."""

    __slots__ = ("_queue", "user_id", "_allowed", "_no_filter", "_cache_ts")

    def __init__(self, user_id: str | None):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.user_id = user_id
        self._allowed: set[str] = set()
        self._no_filter = False
        self._cache_ts = 0.0

    async def get(self):
        return await self._queue.get()

    def offer(self, event: dict) -> bool:
        """Enqueue without blocking. Returns False if the queue is full."""
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

    async def _refresh(self) -> None:
        import auth
        ids = await auth.list_accessible_project_ids(self.user_id)
        if ids is None:  # admin — no filter
            self._no_filter = True
            self._allowed = set()
        else:
            self._no_filter = False
            self._allowed = set(ids)
        self._cache_ts = time.monotonic()

    async def visible(self, project_id: str | None) -> bool:
        # System events (no project_id) and the unauthenticated system stream
        # always fan out.
        if project_id is None or self.user_id is None:
            return True
        if (time.monotonic() - self._cache_ts) > _CACHE_TTL_SECONDS:
            await self._refresh()
        return self._no_filter or project_id in self._allowed


async def broadcast(event: dict) -> None:
    pid = event.get("project_id")
    dead: list[_Subscriber] = []
    for sub in list(_subscribers):
        try:
            if await sub.visible(pid):
                if not sub.offer(event):
                    dead.append(sub)
        except Exception:
            # One subscriber's access lookup must never kill the whole fan-out.
            pass
    for sub in dead:
        if sub in _subscribers:
            _subscribers.remove(sub)


def subscribe(user_id: str | None = None) -> _Subscriber:
    sub = _Subscriber(user_id)
    _subscribers.append(sub)
    return sub


def unsubscribe(sub: "_Subscriber") -> None:
    if sub in _subscribers:
        _subscribers.remove(sub)
