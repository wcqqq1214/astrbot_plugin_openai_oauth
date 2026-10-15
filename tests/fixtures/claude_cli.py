"""Offline Claude CLI double, including a real stdio MCP subprocess."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

root = Path(os.environ["CLAUDE_CONFIG_DIR"])
settings = json.loads((root / "scenario.json").read_text())
args = sys.argv[1:]


def emit(value):
    encoded = json.dumps(value)
    if "auth" in args and settings.get("chunked_status"):
        print(encoded[:10], end="", flush=True)
        time.sleep(0.03)
        print(encoded[10:], flush=True)
    else:
        print(encoded, flush=True)


if "auth" in args:
    if settings.get("invalid_status"):
        print("invalid status secret-token")
        raise SystemExit(2)
    emit(
        {
            "loggedIn": settings.get("loggedIn", True),
            "authMethod": settings.get("authMethod", "claude.ai"),
            "email": settings.get("email", "test@example.invalid"),
            "subscriptionType": "max",
            "accessToken": "secret-token-must-not-escape",
        }
    )
    raise SystemExit(0 if settings.get("loggedIn", True) else 1)

(root / "pid").write_text(str(os.getpid()))
(root / "invocation.json").write_text(
    json.dumps(
        {
            "args": args,
            "cwd": os.getcwd(),
            "environment": {
                k: v for k, v in os.environ.items() if k.startswith("ANTHROPIC_")
            },
        }
    )
)


def delta(kind, field, value):
    emit(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {
                    "type": kind,
                    field: value,
                },
            },
        }
    )


with (root / "invocations.jsonl").open("a") as f:
    f.write(json.dumps({"pid": os.getpid(), "args": args}) + "\n")
resuming = "--resume" in args
session = args[args.index("--resume" if resuming else "--session-id") + 1]
project = re.sub(r"[^a-zA-Z0-9]", "-", os.getcwd())
transcript = root / "projects" / project / (session + ".jsonl")
persist = "--no-session-persistence" not in args
if resuming and (settings.get("resume_fails") or not transcript.is_file()):
    raise SystemExit(1)
turn = 0
for line in sys.stdin:
    message = json.loads(line)
    if message.get("type") == "control_request":
        emit(
            {
                "type": "control_response",
                "response": {
                    "request_id": message["request_id"],
                    "subtype": "success",
                    "response": {},
                },
            }
        )
        continue
    turn += 1
    (root / "prompt.json").write_text(json.dumps(message))
    with (root / "inputs.jsonl").open("a") as f:
        f.write(
            json.dumps({"pid": os.getpid(), "session": session, "message": message})
            + "\n"
        )
    if persist:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        with transcript.open("a") as f:
            f.write(json.dumps(message) + "\n")
    if settings.get("hang") or settings.get("hang_on_turn") == turn:
        time.sleep(60)
        raise SystemExit(1)
    if settings.get("exit_early"):
        print("secret-token", file=sys.stderr)
        raise SystemExit(1)
    delta("thinking_delta", "thinking", "Thinking")
    delta("text_delta", "text", "Hello ")
    if (
        settings.get("hang_after_delta")
        or settings.get("hang_after_delta_on_turn") == turn
    ):
        time.sleep(60)
    reply = "world"
    if settings.get("tool"):
        config = json.loads(args[args.index("--mcp-config") + 1])["mcpServers"][
            "astrbot"
        ]
        helper = subprocess.Popen(
            [config["command"], *config["args"]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

        def rpc(method, params=None, helper=helper):
            helper.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": method,
                        "params": params or {},
                    }
                )
                + "\n"
            )
            helper.stdin.flush()
            return json.loads(helper.stdout.readline())["result"]

        rpc("initialize")
        tools = rpc("tools/list")["tools"]
        (root / "tools.json").write_text(json.dumps(tools))
        for i in range(settings.get("tool_rounds", 1)):
            result = rpc(
                "tools/call", {"name": tools[0]["name"], "arguments": {"value": i}}
            )
            (root / "tool_reply.json").write_text(json.dumps(result))
            reply = result["content"][0]["text"]
        helper.terminate()
        helper.wait()
    delta("text_delta", "text", reply)
    answer = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello " + reply}],
        },
    }
    if persist:
        with transcript.open("a") as f:
            f.write(json.dumps(answer) + "\n")
    emit(answer)
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": session,
            "result": "Hello " + reply,
            "usage": {
                "input_tokens": 3,
                "cache_creation_input_tokens": 5,
                "cache_read_input_tokens": 7,
                "output_tokens": 11,
            },
        }
    )
    if settings.get("exit_after_result"):
        raise SystemExit(0)
