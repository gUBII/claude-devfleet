"""HITL — Human-in-the-Loop shared state registry.

Holds asyncio Futures keyed by session_id. The MCP subprocess creates a
future via create(), blocks the long-poll HTTP call until the future is
resolved via resolve(), then returns the user's reply to the agent.
"""

import asyncio

HITL_TIMEOUT_SECONDS = 600  # 10 minutes

_hitl_futures: dict[str, asyncio.Future] = {}


def create(session_id: str) -> asyncio.Future:
    loop = asyncio.get_running_loop()
    existing = _hitl_futures.pop(session_id, None)
    if existing and not existing.done():
        existing.cancel()
    fut = loop.create_future()
    _hitl_futures[session_id] = fut
    return fut


def resolve(session_id: str, text: str) -> bool:
    fut = _hitl_futures.pop(session_id, None)
    if fut and not fut.done():
        fut.set_result(text)
        return True
    return False


def cancel(session_id: str) -> None:
    fut = _hitl_futures.pop(session_id, None)
    if fut and not fut.done():
        fut.cancel()


def is_waiting(session_id: str) -> bool:
    return session_id in _hitl_futures
