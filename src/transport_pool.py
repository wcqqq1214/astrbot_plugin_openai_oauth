"""Per-account HTTP transports reused between Codex requests."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any


class _PooledTransport:
    __slots__ = ("client", "fingerprint", "retired", "users")

    def __init__(self, fingerprint: tuple[str, str], client: Any) -> None:
        self.fingerprint = fingerprint
        self.client = client
        self.users = 0
        self.retired = False


class TransportPool:
    """Reuse one HTTP transport per account source between requests.

    Reusing a transport keeps its TCP and TLS connections alive. Each source
    gets its own transport, so cookies set for one account never travel with
    another. A transport is replaced when its account or proxy changes and is
    closed once the requests still using it finish.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _PooledTransport] = {}

    @property
    def clients(self) -> list[Any]:
        return [entry.client for entry in self._entries.values()]

    @asynccontextmanager
    async def lease(
        self,
        source_id: str,
        fingerprint: tuple[str, str],
        create: Callable[[], Any],
    ):
        entry = self._entries.get(source_id)
        if entry is None or entry.fingerprint != fingerprint or entry.client.is_closed:
            if entry is not None:
                await self._retire(entry)
            entry = _PooledTransport(fingerprint, create())
            self._entries[source_id] = entry
        entry.users += 1
        try:
            yield entry.client
        finally:
            entry.users -= 1
            if entry.retired and entry.users == 0:
                await entry.client.aclose()

    async def _retire(self, entry: _PooledTransport) -> None:
        entry.retired = True
        if entry.users == 0:
            await entry.client.aclose()

    async def close(self) -> None:
        entries = list(self._entries.values())
        self._entries.clear()
        for entry in entries:
            entry.retired = True
            await entry.client.aclose()
