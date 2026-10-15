"""No-network integration tests for local Claude and parked MCP tool turns."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
ASTRBOT_ROOT = ROOT.parent / "AstrBot"
sys.path.insert(0, str(ASTRBOT_ROOT))
os.chdir(ASTRBOT_ROOT)
module = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.claude_provider"
)
local = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.local_claude")
bridge_module = importlib.import_module(
    "data.plugins.astrbot_plugin_openai_oauth.claude_bridge"
)
plugin = importlib.import_module("data.plugins.astrbot_plugin_openai_oauth.main")


class ClaudeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop_errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, ctx: self.loop_errors.append(ctx)
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "account"
        self.config.mkdir()
        self.scenario = {}
        self.save_scenario()
        self.binary = self.root / "fake claude"
        self.binary.write_text(
            "#!"
            + sys.executable
            + "\n"
            + (ROOT / "tests/fixtures/claude_cli.py").read_text()
        )
        self.binary.chmod(0o700)
        self.host = local.LocalClaude(str(self.binary), str(self.config))
        self.bridge = bridge_module.ClaudeBridge(self.host, self.root / "runs", 15)
        self.addAsyncCleanup(self.bridge.close)
        self.payload = {
            "model": "sonnet",
            "system": [{"type": "text", "text": "Be concise"}],
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hello"}]}
            ],
        }
        self.tools = [
            {
                "name": "lookup",
                "description": "Look up a value",
                "input_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            }
        ]

    async def asyncTearDown(self):
        await self.bridge.close()
        await asyncio.sleep(0)
        self.assertEqual(self.loop_errors, [])

    def save_scenario(self):
        (self.config / "scenario.json").write_text(json.dumps(self.scenario))

    async def collect(self, payload=None, tools=None, owner="chat-a"):
        return [
            r
            async for r in self.bridge.stream(
                payload or self.payload, tools or [], owner=owner
            )
        ]

    def tool_payload(self, response, base=None, text="tool answer"):
        payload = deepcopy(base or self.payload)
        payload["messages"] += [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": response.tools_call_name[0],
                        "id": response.tools_call_ids[0],
                        "input": response.tools_call_args[0],
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": response.tools_call_ids[0],
                        "content": text,
                    }
                ],
            },
        ]
        return payload

    async def test_status_is_sanitized_and_tracks_logout(self):
        status = await self.host.status()
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["plan_type"], "max")
        self.assertNotIn("secret", json.dumps(status))
        self.scenario["loggedIn"] = False
        self.save_scenario()
        self.assertEqual((await self.host.status())["status"], "not_logged_in")
        with self.assertRaises(local.ClaudeError):
            await self.collect()
        self.assertFalse((self.config / "pid").exists())

    async def test_status_reads_all_stdout_chunks(self):
        self.scenario["chunked_status"] = True
        self.save_scenario()
        self.assertEqual((await self.host.status())["status"], "ready")

    async def test_missing_cli_wrong_auth_and_malformed_status(self):
        self.assertEqual(
            (await local.LocalClaude("/no/such/claude").status())["status"],
            "cli_missing",
        )
        for method in ("api_key", "third_party", "oauth_token"):
            self.scenario["authMethod"] = method
            self.save_scenario()
            self.assertEqual((await self.host.status())["status"], "wrong_auth")
        self.scenario["invalid_status"] = True
        self.save_scenario()
        self.assertEqual(await self.host.status(), {"status": "unknown"})

    async def test_stream_content_usage_and_environment_isolation(self):
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "secret-api",
                "ANTHROPIC_BASE_URL": "http://gateway",
                "CLAUDE_CODE_OAUTH_TOKEN": "secret-token",
                "CLAUDE_CODE_USE_BEDROCK": "1",
            },
        ):
            replies = await self.collect()
        final = replies[-1]
        self.assertFalse(final.is_chunk)
        self.assertEqual(final.completion_text, "Hello world")
        self.assertEqual(final.reasoning_content, "Thinking")
        self.assertEqual(final.usage.input_other, 8)
        self.assertEqual(final.usage.input_cached, 7)
        self.assertEqual(final.usage.output, 11)
        self.assertEqual(
            "".join(r.completion_text or "" for r in replies if r.is_chunk),
            "Hello world",
        )
        invocation = json.loads((self.config / "invocation.json").read_text())
        self.assertEqual(invocation["environment"], {})
        self.assertNotIn("--dangerously-skip-permissions", invocation["args"])
        self.assertEqual(
            invocation["args"][invocation["args"].index("--tools") + 1], ""
        )
        prompt = (self.config / "prompt.json").read_text()
        self.assertIn("Be concise", prompt)
        self.assertIn("hello", prompt)
        self.assertEqual(len(self.bridge.runs), 1)
        self.assertTrue(next(iter(self.bridge.runs)).idle)

    async def test_real_mcp_helper_round_trip_and_repeated_tool_turns(self):
        self.scenario.update(tool=True, tool_rounds=2)
        self.save_scenario()
        first = (await self.collect(tools=self.tools))[-1]
        self.assertEqual(first.tools_call_name, ["lookup"])
        self.assertEqual(first.tools_call_args, [{"value": 0}])
        self.assertEqual(len(self.bridge.runs), 1)
        payload = self.tool_payload(first)
        second = (await self.collect(payload, self.tools))[-1]
        self.assertEqual(second.tools_call_args, [{"value": 1}])
        final = (
            await self.collect(self.tool_payload(second, payload, "done"), self.tools)
        )[-1]
        self.assertEqual(final.completion_text, "done")
        self.assertTrue(next(iter(self.bridge.runs)).idle)
        advertised = json.loads((self.config / "tools.json").read_text())
        self.assertEqual(advertised[0]["inputSchema"], self.tools[0]["input_schema"])

    async def test_tool_session_cannot_cross_chat_or_account(self):
        self.scenario["tool"] = True
        self.save_scenario()
        first = (await self.collect(tools=self.tools))[-1]
        payload = self.tool_payload(first)
        with self.assertRaisesRegex(local.ClaudeError, "match"):
            await self.collect(payload, self.tools, owner="chat-b")
        self.scenario["email"] = "changed@example.invalid"
        self.save_scenario()
        with self.assertRaisesRegex(local.ClaudeError, "match"):
            await self.collect(payload, self.tools)
        await self.bridge.close()
        with self.assertRaisesRegex(local.ClaudeError, "stopped"):
            await self.collect(payload, self.tools)

    async def test_timeout_cancellation_and_unload_reap_processes(self):
        self.scenario["hang"] = True
        self.save_scenario()
        self.bridge.timeout = 0.5
        with self.assertRaisesRegex(local.ClaudeError, "timed out"):
            await self.collect()
        pid = int((self.config / "pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertFalse(self.bridge.runs)
        self.bridge.timeout = 15
        task = asyncio.create_task(self.collect())
        for _ in range(100):
            await asyncio.sleep(0.02)
            if any(run.process for run in self.bridge.runs):
                break
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.bridge.runs)

    async def test_cli_failure_never_exposes_stderr(self):
        self.scenario["exit_early"] = True
        self.save_scenario()
        with self.assertRaises(local.ClaudeError) as caught:
            await self.collect()
        self.assertNotIn("secret", str(caught.exception))
        self.assertFalse(self.bridge.runs)

    async def test_provider_uses_astrbot_context_conversion(self):
        source = {
            **local.default_claude_source(),
            "model": "sonnet",
            "claude_command": str(self.binary),
            "claude_config_dir": str(self.config),
        }
        provider = module.ProviderLocalClaude(source, {})
        provider.bridge.root = self.root / "provider-runs"
        self.addAsyncCleanup(provider.terminate)
        result = await provider.text_chat(
            prompt="new",
            contexts=[{"role": "user", "content": "old"}],
            system_prompt="Be brief",
        )
        self.assertEqual(result.completion_text, "Hello world")
        prompt = (self.config / "prompt.json").read_text()
        self.assertIn("Be brief", prompt)
        self.assertIn("old", prompt)
        self.assertIn("new", prompt)
        self.assertEqual(await provider.get_models(), ["sonnet", "opus", "haiku"])
        self.assertEqual(provider.get_current_key(), "")
        self.assertEqual(source["key"], "")

    def next_turn(self, response, payload=None, text="next question"):
        payload = deepcopy(payload or self.payload)
        payload["messages"] += [
            {"role": "assistant", "content": response.completion_text},
            {"role": "user", "content": text},
        ]
        return payload

    def inputs(self):
        return [
            json.loads(line)
            for line in (self.config / "inputs.jsonl").read_text().splitlines()
        ]

    async def test_live_turns_send_only_new_messages_and_keep_images_out(self):
        self.payload["messages"][0]["content"].append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "old-image",
                },
            }
        )
        first = (await self.collect())[-1]
        second_payload = self.next_turn(first)
        second = (await self.collect(second_payload))[-1]
        await self.collect(self.next_turn(second, second_payload, "third question"))
        inputs = self.inputs()
        self.assertEqual(len({x["pid"] for x in inputs}), 1)
        self.assertIn("old-image", json.dumps(inputs[0]))
        for item in inputs[1:]:
            text = json.dumps(item["message"])
            self.assertNotIn("old-image", text)
            self.assertNotIn("Be concise", text)
            self.assertNotIn("Hello world", text)
        self.assertNotIn("next question", json.dumps(inputs[2]))
        self.assertIn("third question", json.dumps(inputs[2]))

    async def test_idle_eviction_restores_checkpoint_with_delta(self):
        first = (await self.collect())[-1]
        run = next(iter(self.bridge.runs))
        old_pid = run.process.pid
        await self.bridge.shelve(run)
        self.assertFalse(self.bridge.runs)
        with self.assertRaises(ProcessLookupError):
            os.kill(old_pid, 0)
        await self.collect(self.next_turn(first))
        inputs = self.inputs()
        self.assertNotEqual(inputs[0]["pid"], inputs[1]["pid"])
        self.assertEqual(inputs[0]["session"], inputs[1]["session"])
        self.assertNotIn("hello", json.dumps(inputs[1]["message"]))
        invocation = json.loads((self.config / "invocation.json").read_text())
        self.assertIn("--resume", invocation["args"])

    async def test_provider_restart_restores_saved_session(self):
        first = (await self.collect())[-1]
        await self.bridge.close()
        self.bridge = bridge_module.ClaudeBridge(self.host, self.root / "runs", 15)
        self.addAsyncCleanup(self.bridge.close)
        await self.collect(self.next_turn(first))
        inputs = self.inputs()
        self.assertEqual(inputs[0]["session"], inputs[1]["session"])
        self.assertNotIn("hello", json.dumps(inputs[1]["message"]))
        metadata = next(self.bridge.store.records.glob("*/state.json")).read_text()
        self.assertNotIn("next question", metadata)
        self.assertNotIn("test@example", metadata)

    async def test_restore_failure_falls_back_before_sending_user_input(self):
        first = (await self.collect())[-1]
        await self.bridge.shelve(next(iter(self.bridge.runs)))
        self.scenario["resume_fails"] = True
        self.save_scenario()
        await self.collect(self.next_turn(first))
        inputs = self.inputs()
        self.assertEqual(len(inputs), 2)
        self.assertNotEqual(inputs[0]["session"], inputs[1]["session"])
        self.assertIn("hello", json.dumps(inputs[1]["message"]))
        self.assertIn("next question", json.dumps(inputs[1]["message"]))
        starts = (self.config / "invocations.jsonl").read_text().splitlines()
        self.assertEqual(len(starts), 3)

    async def test_dead_idle_process_restores_without_replaying_history(self):
        self.scenario["exit_after_result"] = True
        self.save_scenario()
        first = (await self.collect())[-1]
        run = next(iter(self.bridge.runs))
        await run.process.wait()
        await self.collect(self.next_turn(first))
        inputs = self.inputs()
        self.assertEqual(inputs[0]["session"], inputs[1]["session"])
        self.assertNotIn("hello", json.dumps(inputs[1]["message"]))

    async def test_changed_owner_account_settings_and_history_start_fresh(self):
        first = (await self.collect())[-1]
        original_session = self.inputs()[0]["session"]
        following = self.next_turn(first)
        cases = []
        for field, value in (("model", "opus"), ("system", "Different persona")):
            payload = deepcopy(following)
            payload[field] = value
            cases.append((payload, [], "chat-a", ""))
        edited = deepcopy(following)
        edited["messages"][0]["content"] = "edited history"
        cases += [
            (edited, [], "chat-a", ""),
            (following, [], "chat-b", ""),
            (following, self.tools, "chat-a", ""),
            (following, [], "chat-a", "high"),
        ]
        for payload, tools, owner, effort in cases:
            with self.subTest(owner=owner, effort=effort, payload=payload):
                _ = [
                    r
                    async for r in self.bridge.stream(
                        payload, tools, owner=owner, effort=effort
                    )
                ]
                self.assertNotEqual(self.inputs()[-1]["session"], original_session)
                self.assertIn("History", json.dumps(self.inputs()[-1]["message"]))
        self.scenario["email"] = "other@example.invalid"
        self.save_scenario()
        await self.collect(following)
        self.assertNotEqual(self.inputs()[-1]["session"], original_session)
        await self.collect()
        self.assertNotEqual(self.inputs()[-1]["session"], original_session)

    async def test_concurrent_branches_never_share_a_busy_process(self):
        first = (await self.collect())[-1]
        payload = self.next_turn(first)
        await asyncio.gather(self.collect(payload), self.collect(payload))
        inputs = self.inputs()
        self.assertNotEqual(inputs[1]["session"], inputs[2]["session"])
        self.assertEqual(
            sum("hello" in json.dumps(i["message"]) for i in inputs[1:]), 1
        )

    async def test_cancelled_continuation_is_not_checkpointed_or_retried(self):
        self.scenario["hang_after_delta_on_turn"] = 2
        self.save_scenario()
        first = (await self.collect())[-1]
        payload = self.next_turn(first)
        responses = self.bridge.stream(payload, [], owner="chat-a")
        async for response in responses:
            if response.completion_text:
                break
        await responses.aclose()
        self.assertFalse(self.bridge.runs)
        self.assertEqual(list(self.bridge.store.records.iterdir()), [])
        self.assertEqual(len(self.inputs()), 2)
        await self.collect(payload)
        self.assertNotEqual(self.inputs()[0]["session"], self.inputs()[2]["session"])
        self.assertIn("hello", json.dumps(self.inputs()[2]["message"]))

    async def test_tool_round_then_next_user_turn_reuses_process(self):
        self.scenario["tool"] = True
        self.save_scenario()
        called = (await self.collect(tools=self.tools))[-1]
        answered = self.tool_payload(called)
        final = (await self.collect(answered, self.tools))[-1]
        following = self.next_turn(final, answered)
        next_call = (await self.collect(following, self.tools))[-1]
        self.assertEqual(next_call.tools_call_name, ["lookup"])
        inputs = self.inputs()
        self.assertEqual(inputs[0]["pid"], inputs[1]["pid"])
        self.assertNotIn("tool answer", json.dumps(inputs[1]["message"]))

    async def test_tool_images_after_results_resume_the_waiting_process(self):
        self.scenario["tool"] = True
        self.save_scenario()
        called = (await self.collect(tools=self.tools))[-1]
        payload = self.tool_payload(called)
        payload["messages"].append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Image from tool lookup"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "image-data",
                        },
                    },
                ],
            }
        )
        final = (await self.collect(payload, self.tools))[-1]
        self.assertEqual(final.completion_text, "tool answer")
        self.assertEqual(len(self.inputs()), 1)
        content = json.loads((self.config / "tool_reply.json").read_text())["content"]
        self.assertIn(
            {"type": "image", "data": "image-data", "mimeType": "image/png"}, content
        )
        self.assertTrue(next(iter(self.bridge.runs)).idle)

    async def test_bounded_idle_pool_and_expired_saved_sessions(self):
        self.bridge.max_idle = 1
        first = (await self.collect())[-1]
        first_session = self.inputs()[0]["session"]
        await self.collect(owner="chat-b")
        await self.bridge.trim_idle()
        self.assertEqual(len(self.bridge.runs), 1)
        state_path = self.bridge.store.directory(first_session) / "state.json"
        state = json.loads(state_path.read_text())
        state["updated"] = 0
        state_path.write_text(json.dumps(state))
        await self.collect(self.next_turn(first))
        self.assertNotEqual(self.inputs()[-1]["session"], first_session)
        self.assertFalse(state_path.parent.exists())

    async def test_no_owner_or_unavailable_persistence_still_answers(self):
        first = (await self.collect(owner=None))[-1]
        self.assertFalse(self.bridge.runs)
        await self.collect(self.next_turn(first), owner=None)
        self.assertNotEqual(self.inputs()[0]["session"], self.inputs()[1]["session"])
        with patch.object(self.bridge.store, "prepare", return_value=False):
            first = (await self.collect())[-1]
            await self.collect(self.next_turn(first))
            self.assertEqual(self.inputs()[-2]["pid"], self.inputs()[-1]["pid"])
            await self.bridge.shelve(next(iter(self.bridge.runs)))
        self.assertEqual(list(self.bridge.store.records.iterdir()), [])

    async def test_second_bridge_cannot_restore_or_delete_live_session(self):
        first = (await self.collect())[-1]
        original = next(iter(self.bridge.runs))
        other = bridge_module.ClaudeBridge(self.host, self.root / "runs", 15)
        self.addAsyncCleanup(other.close)
        payload = self.next_turn(first)
        _ = [r async for r in other.stream(payload, [], owner="chat-a")]
        self.assertNotEqual(next(iter(other.runs)).session, original.session)
        self.assertTrue(original.directory.exists())
        self.assertIsNone(original.process.returncode)
        await self.collect(payload)
        self.assertEqual(self.inputs()[-1]["session"], original.session)

    async def test_provider_session_id_reaches_reuse_on_older_astrbot(self):
        provider = module.ProviderLocalClaude(
            {
                **local.default_claude_source(),
                "model": "sonnet",
                "claude_command": str(self.binary),
                "claude_config_dir": str(self.config),
            },
            {},
        )
        provider.bridge.root = self.root / "provider-runs"
        self.addAsyncCleanup(provider.terminate)
        first = await provider.text_chat(prompt="old", session_id="umo-a")
        await provider.text_chat(
            prompt="new",
            session_id="umo-a",
            contexts=[
                {"role": "user", "content": "old"},
                {"role": "assistant", "content": first.completion_text},
            ],
        )
        inputs = self.inputs()
        self.assertEqual(inputs[0]["pid"], inputs[1]["pid"])
        self.assertNotIn("old", json.dumps(inputs[1]["message"]))

    async def test_public_stream_can_be_read_and_closed_in_different_tasks(self):
        provider = module.ProviderLocalClaude(
            {
                **local.default_claude_source(),
                "model": "sonnet",
                "claude_command": str(self.binary),
                "claude_config_dir": str(self.config),
            },
            {},
        )
        provider.bridge.root = self.root / "provider-stream"
        self.addAsyncCleanup(provider.terminate)
        stream = provider.text_chat_stream(prompt="hello", session_id="umo-stream")
        try:
            while True:
                try:
                    await asyncio.create_task(anext(stream))
                except StopAsyncIteration:
                    break
        finally:
            await asyncio.create_task(stream.aclose())
        self.assertTrue(next(iter(provider.bridge.runs)).idle)

    async def test_public_stream_close_reaps_cli_before_returning(self):
        self.scenario["hang_after_delta"] = True
        self.save_scenario()
        provider = module.ProviderLocalClaude(
            {
                **local.default_claude_source(),
                "model": "sonnet",
                "claude_command": str(self.binary),
                "claude_config_dir": str(self.config),
            },
            {},
        )
        provider.bridge.root = self.root / "provider-stream"
        self.addAsyncCleanup(provider.terminate)
        stream = provider.text_chat_stream(prompt="hello", session_id="umo-stream")
        await asyncio.create_task(anext(stream))
        await asyncio.create_task(stream.aclose())
        self.assertFalse(provider.bridge.runs)
        pid = int((self.config / "pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    async def test_registry_adds_claude_without_touching_codex(self):
        class Config(dict):
            async def save_config_async(self):
                return True

        conf = Config(provider_sources=[plugin._build_default_source_config()])
        with patch.object(plugin, "_config_mgr", SimpleNamespace(default_conf=conf)):
            coordinator = plugin._get_credential_coordinator()
            original = deepcopy(conf["provider_sources"][0])
            await module.ensure_source(coordinator.providers)
            await module.ensure_source(coordinator.providers)
            self.assertEqual(len(conf["provider_sources"]), 2)
            self.assertEqual(conf["provider_sources"][0], original)
            with (
                patch.object(plugin, "_login_request_error", return_value=None),
                patch.object(
                    module,
                    "account_view",
                    new=AsyncMock(
                        return_value={"id": "Claude Subscribe", "status": "ready"}
                    ),
                ),
            ):
                response = await plugin._handle_providers_list()
                self.assertNotIn("secret", str(response))


if __name__ == "__main__":
    unittest.main()
