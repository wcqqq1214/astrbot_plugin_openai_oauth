"""Stdio MCP transport for Claude Code; AstrBot remains the tool executor.

Invoked as a standalone script by the official CLI. The private callback file
holds a per-run capability, so no credential appears in the process arguments.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx


async def main() -> None:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tasks: set[asyncio.Task] = set()
    output_lock = asyncio.Lock()
    async with httpx.AsyncClient(trust_env=False, timeout=600) as client:

        async def answer(message: dict) -> None:
            if "id" not in message:
                return
            try:
                response = await client.post(
                    config["url"],
                    json=message,
                    headers={"Authorization": "Bearer " + config["token"]},
                )
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError):
                body = {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {
                        "code": -32603,
                        "message": "AstrBot tool bridge is unavailable.",
                    },
                }
            async with output_lock:
                print(json.dumps(body, ensure_ascii=False), flush=True)

        try:
            while line := await asyncio.to_thread(sys.stdin.buffer.readline):
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                task = asyncio.create_task(answer(message))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
