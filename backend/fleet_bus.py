"""
Shared in-process event bus for fleet-wide SSE.
Imported by both app.py (route) and sdk_engine.py (emitters) to avoid circular deps.
"""
import asyncio

_subscribers: list[asyncio.Queue] = []


async def broadcast(event: dict) -> None:
    dead: list[asyncio.Queue] = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        if q in _subscribers:
            _subscribers.remove(q)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)
