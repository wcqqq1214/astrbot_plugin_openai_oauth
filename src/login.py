"""Device-login sessions, credential persistence, and task cleanup."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain

from . import oauth, runtime
from .credential_store import CredentialSourceError
from .oauth import (
    CODEX_DEVICE_VERIFY_URL,
    DeviceAuthError,
    DeviceAuthTimeout,
)

_LOGIN_RESULT_TTL_SECONDS = 120

# Both command and WebUI login tasks are owned and cleaned up here.
_command_login_tasks: dict[str, asyncio.Task[Any]] = {}
_login_sessions: dict[str, dict] = {}


def _is_private_login_event(event: AstrMessageEvent) -> bool:
    """Return whether the event is a direct message, failing closed if unknown."""
    checker = getattr(event, "is_private_chat", None)
    return callable(checker) and bool(checker())


def _command_login_owner(event: AstrMessageEvent) -> str:
    """Build a non-secret owner key for one private command session."""
    try:
        owner = str(event.unified_msg_origin or "").strip()
    except (AttributeError, TypeError):
        owner = ""
    return owner or f"event:{id(event)}"


def _release_command_login_task(owner: str, task: asyncio.Task[Any]) -> None:
    if _command_login_tasks.get(owner) is task:
        _command_login_tasks.pop(owner, None)


def _cancel_all_command_login_tasks() -> list[asyncio.Task[Any]]:
    tasks = list(set(_command_login_tasks.values()))
    _command_login_tasks.clear()
    for task in tasks:
        if not task.done():
            task.cancel()
    return tasks


def _discard_login_session(session_id: str, *, cancel_task: bool = True) -> None:
    session = _login_sessions.pop(session_id, None)
    if session is None:
        return
    expiry_handle = session.get("expiry_handle")
    if expiry_handle is not None:
        expiry_handle.cancel()
    task = session.get("task")
    if cancel_task and task is not None and not task.done():
        task.cancel()


def _discard_all_login_sessions() -> None:
    for session_id in list(_login_sessions):
        _discard_login_session(session_id)


def _schedule_login_session_expiry(session_id: str, delay: float) -> None:
    session = _login_sessions.get(session_id)
    if session is None:
        return
    old_handle = session.get("expiry_handle")
    if old_handle is not None:
        old_handle.cancel()
    session["expires_at"] = time.monotonic() + delay
    session["expiry_handle"] = asyncio.get_running_loop().call_later(
        delay, _discard_login_session, session_id
    )


def _prune_expired_login_sessions() -> None:
    now = time.monotonic()
    expired = [
        session_id
        for session_id, session in _login_sessions.items()
        if float(session.get("expires_at", 0)) <= now
    ]
    for session_id in expired:
        _discard_login_session(session_id)


async def _persist_login_credentials(
    creds: dict[str, Any],
    *,
    source_id: str | None = None,
    name: str = "ChatGPT",
    creating: bool = True,
) -> str:
    """Persist only the provider bound to the server-owned device session."""
    registry = runtime._get_credential_coordinator().providers
    source_id = source_id or registry.new_id()
    await registry.save_login(source_id, name, creds, creating=creating)
    return source_id


async def _complete_device_login(
    *,
    device_auth_id: str,
    user_code: str,
    interval: int,
    proxy: str,
) -> dict:
    """Poll, exchange, and build credentials for one device challenge."""
    authorization_code, code_verifier = await oauth.poll_device_authorization(
        device_auth_id,
        user_code,
        interval,
        proxy,
    )
    tokens = await oauth.exchange_authorization_code(
        authorization_code,
        code_verifier,
        proxy,
    )
    return oauth.build_credentials(
        tokens["access_token"],
        tokens.get("refresh_token", ""),
        tokens.get("expires_in", 3600),
    )


async def _run_device_login(session_id: str, proxy: str) -> None:
    session = _login_sessions.get(session_id)
    if session is None:
        return
    try:
        creds = await _complete_device_login(
            device_auth_id=session["device_auth_id"],
            user_code=session["user_code"],
            interval=session["interval"],
            proxy=proxy,
        )
        session["status"] = "saving"
        await _persist_login_credentials(
            creds,
            source_id=session["source_id"],
            name=session["name"],
            creating=session["creating"],
        )
        session["status"] = "success"
        logger.info("OpenAI Codex device login succeeded.")
    except asyncio.CancelledError:
        raise
    except DeviceAuthTimeout as exc:
        session["status"] = "timeout"
        session["error"] = str(exc)
    except DeviceAuthError as exc:
        session["status"] = "error"
        session["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - report a generic error without credential data
        session["status"] = "error"
        session["error"] = "登录或保存失败，请重试"
        logger.error("OpenAI Codex device login failed: %s", type(exc).__name__)
    finally:
        if _login_sessions.get(session_id) is session:
            _schedule_login_session_expiry(session_id, _LOGIN_RESULT_TTL_SECONDS)


async def _run_command_device_login(
    event: AstrMessageEvent,
    device_auth_id: str,
    user_code: str,
    interval: int,
    proxy: str,
) -> None:
    """Complete a private-command login without exposing credential material."""
    try:
        creds = await _complete_device_login(
            device_auth_id=device_auth_id,
            user_code=user_code,
            interval=interval,
            proxy=proxy,
        )
        source_id = await _persist_login_credentials(creds)
    except asyncio.CancelledError:
        raise
    except DeviceAuthTimeout:
        await event.send(
            MessageChain().message("设备码已过期，请重新发送 /openai_login。")
        )
    except DeviceAuthError as exc:
        await event.send(MessageChain().message(f"OpenAI 登录失败：{exc}"))
    except Exception as exc:  # noqa: BLE001 - never send provider or credential details
        logger.error("OpenAI Codex admin device login failed: %s", type(exc).__name__)
        await event.send(MessageChain().message("OpenAI 登录或保存失败，请重试。"))
    else:
        await event.send(
            MessageChain().message(
                f"OpenAI 登录成功，已新增 Provider：{source_id}。请在模型配置中选择此来源。"
            )
        )


async def handle_login(event: AstrMessageEvent) -> None:
    """Add a provider through administrator-only private-chat device login."""
    event.should_call_llm(False)
    if not _is_private_login_event(event):
        await event.send(
            MessageChain().message(
                "为保护设备码，/openai_login 仅允许在管理员私聊中使用。"
            )
        )
        return

    owner = _command_login_owner(event)
    existing_task = _command_login_tasks.get(owner)
    if existing_task is not None and not existing_task.done():
        await event.send(
            MessageChain().message(
                "当前私聊已有一个 OpenAI 登录流程，请先完成或等待它结束。"
            )
        )
        return

    current_task = asyncio.current_task()
    if current_task is not None:
        _command_login_tasks[owner] = current_task
    try:
        proxy = runtime._get_credential_coordinator().source_settings()["proxy"]
    except CredentialSourceError:
        proxy = ""
    try:
        try:
            device_auth_id, user_code, interval = await oauth.request_device_user_code(
                proxy
            )
        except DeviceAuthError as exc:
            await event.send(MessageChain().message(f"无法启动设备登录：{exc}"))
            return
        except Exception as exc:  # noqa: BLE001 - keep network details out of chat
            logger.error(
                "OpenAI Codex admin device-code request failed: %s",
                type(exc).__name__,
            )
            await event.send(MessageChain().message("无法启动设备登录，请稍后重试。"))
            return

        await event.send(
            MessageChain().message(
                "请在当前私聊中打开以下 OpenAI 验证网址并输入设备码：\n"
                f"{CODEX_DEVICE_VERIFY_URL}\n"
                f"设备码：{user_code}\n"
                "授权完成后，AstrBot 会在服务端自动交换并保存凭据；令牌不会发送到聊天。"
            )
        )
        task = asyncio.create_task(
            _run_command_device_login(
                event,
                device_auth_id,
                user_code,
                interval,
                proxy,
            )
        )
        _command_login_tasks[owner] = task
        task.add_done_callback(lambda done: _release_command_login_task(owner, done))
    finally:
        if current_task is not None and _command_login_tasks.get(owner) is current_task:
            _command_login_tasks.pop(owner, None)


async def terminate() -> None:
    """Cancel all outstanding device-login work during plugin unload."""
    _discard_all_login_sessions()
    tasks = _cancel_all_command_login_tasks()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
