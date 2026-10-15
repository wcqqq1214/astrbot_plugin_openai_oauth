"""Opt-in native CLI check with an isolated home and loopback-only model fixture.

Run with AstrBot's Python: tests/native_claude_smoke.py --binary /path/to/claude
No subscription credentials are read; the model API uses a dummy test key.
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from run_tests import CheckoutFinder

sys.meta_path.insert(0, CheckoutFinder())
sys.path.insert(0, str(ROOT.parent / "AstrBot"))
os.chdir(ROOT.parent / "AstrBot")
local = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.local_claude")
bridge = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.claude_bridge"
)


async def main(binary):
    with tempfile.TemporaryDirectory(prefix="astrbot-native-cli-") as tmp:
        root = Path(tmp)
        requests = []

        async def api(request):
            if not request.path.endswith("/messages"):
                return web.json_response({"input_tokens": 1})
            body = await request.json()
            requests.append(body)
            msg = {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 3, "output_tokens": 0},
            }
            if not body.get("stream"):
                return web.json_response(
                    {
                        **msg,
                        "content": [{"type": "text", "text": "native reply"}],
                        "stop_reason": "end_turn",
                    }
                )
            events = [
                {"type": "message_start", "message": msg},
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "native reply"},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 2},
                },
                {"type": "message_stop"},
            ]
            return web.Response(
                text="".join(
                    "event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n"
                    for e in events
                ),
                content_type="text/event-stream",
            )

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", api)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]

        class Host(local.LocalClaude):
            def environment(self):
                env = super().environment()
                env.update(
                    HOME=str(root),
                    CLAUDE_CONFIG_DIR=str(root / "config"),
                    ANTHROPIC_BASE_URL=f"http://127.0.0.1:{port}",
                    ANTHROPIC_API_KEY="test-local-only",
                    DISABLE_AUTOUPDATER="1",
                    DISABLE_TELEMETRY="1",
                    DISABLE_ERROR_REPORTING="1",
                )
                return env

            async def require_login(self):
                return {"status": "ready", "email": "local-fixture@example.invalid"}

        host = Host(binary, str(root / "config"))
        b = bridge.ClaudeBridge(host, root / "data", 45)
        p = {
            "model": "sonnet",
            "messages": [{"role": "user", "content": "first-marker"}],
        }

        async def collect():
            out = [r async for r in b.stream(p, [], owner="native-test")]
            assert out[-1].completion_text == "native reply", out[-1]
            assert out[-1].usage.input_other == 3, out[-1].usage
            assert out[-1].usage.output == 2, out[-1].usage

        try:
            await collect()
            run = next(iter(b.runs))
            pid = run.process.pid
            sid = run.session
            print(
                "First native turn completed, checkpoint:",
                (b.store.transcripts / (sid + ".jsonl")).exists(),
                flush=True,
            )
            p["messages"] += [
                {"role": "assistant", "content": "native reply"},
                {"role": "user", "content": "second-marker"},
            ]
            await collect()
            assert next(iter(b.runs)).process.pid == pid
            print("Native process reused for second turn", flush=True)
            await b.shelve(next(iter(b.runs)))
            p["messages"] += [
                {"role": "assistant", "content": "native reply"},
                {"role": "user", "content": "third-marker"},
            ]
            await collect()
            run = next(iter(b.runs))
            assert run.session == sid and run.process.pid != pid
            print("Native resume succeeded; model requests:", len(requests), flush=True)
        finally:
            await b.close()
            await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary",
        required=True,
        help="Absolute path to the official Claude Code binary",
    )
    asyncio.run(main(parser.parse_args().binary))
