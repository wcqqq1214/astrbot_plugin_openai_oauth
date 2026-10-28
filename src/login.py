"""Device-login sessions, credential persistence, and task cleanup."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain

from . import messages, oauth, runtime
from .credential_store import CredentialSourceError, token_email
from .oauth import (
    CODEX_DEVICE_LOGIN_TIMEOUT,
    CODEX_DEVICE_VERIFY_URL,
    DeviceAuthError,
    DeviceAuthTimeout,
)

_LOGIN_RESULT_TTL_SECONDS = 120


class LoginStatus(StrEnum):
    STARTING = "starting"
    PENDING = "pending"
    SAVING = "saving"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


ACTIVE_STATUSES = frozenset(
    {LoginStatus.STARTING, LoginStatus.PENDING, LoginStatus.SAVING}
)
FINISHED_STATUSES = frozenset(
    {LoginStatus.SUCCESS, LoginStatus.ERROR, LoginStatus.TIMEOUT}
)


@dataclass(eq=False)
class DeviceLoginSession:
    """One WebUI device login, owned by the dashboard user who started it."""

    owner: str
    source_id: str = ""
    name: str = ""
    creating: bool = True
    status: LoginStatus = LoginStatus.STARTING
    device_auth_id: str | None = None
    user_code: str | None = None
    interval: int | None = None
    error: str | None = None
    task: asyncio.Task[Any] | None = None
    expiry_handle: asyncio.TimerHandle | None = None
    expires_at: float = 0.0


# Both command and WebUI login tasks are owned and cleaned up here.
_command_login_tasks: dict[str, asyncio.Task[Any]] = {}
_committing_command_login_tasks: set[asyncio.Task[Any]] = set()
_login_sessions: dict[str, DeviceLoginSession] = {}


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
        if not task.done() and task not in _committing_command_login_tasks:
            task.cancel()
    return tasks


def discard_session(session_id: str, *, cancel_task: bool = True) -> None:
    session = _login_sessions.pop(session_id, None)
    if session is None:
        return
    if session.expiry_handle is not None:
        session.expiry_handle.cancel()
    task = session.task
    if cancel_task and task is not None and not task.done():
        task.cancel()


def discard_all_sessions() -> None:
    for session_id in list(_login_sessions):
        discard_session(session_id)


def discard_sessions_for_source(source_id: str) -> None:
    for session_id, session in list(_login_sessions.items()):
        if session.source_id == source_id:
            discard_session(session_id)


def schedule_session_expiry(session_id: str, delay: float) -> None:
    session = _login_sessions.get(session_id)
    if session is None:
        return
    if session.expiry_handle is not None:
        session.expiry_handle.cancel()
    session.expires_at = time.monotonic() + delay
    session.expiry_handle = asyncio.get_running_loop().call_later(
        delay, discard_session, session_id
    )


def prune_sessions() -> None:
    now = time.monotonic()
    expired = [
        session_id
        for session_id, session in _login_sessions.items()
        if session.expires_at <= now
    ]
    for session_id in expired:
        discard_session(session_id)


def sessions() -> dict[str, DeviceLoginSession]:
    """Return live sessions after dropping expired ones."""
    prune_sessions()
    return dict(_login_sessions)


def owned_session(session_id: str, owner: str) -> DeviceLoginSession | None:
    """Return a live session only to the dashboard user who started it."""
    prune_sessions()
    session = _login_sessions.get(session_id)
    if session is None or not secrets.compare_digest(session.owner, owner):
        return None
    return session


def reserve_session(session_id: str, session: DeviceLoginSession) -> None:
    """Hold a bounded slot before the first await of a new login."""
    _login_sessions[session_id] = session
    schedule_session_expiry(
        session_id, CODEX_DEVICE_LOGIN_TIMEOUT + _LOGIN_RESULT_TTL_SECONDS
    )


def begin_session(
    session_id: str,
    *,
    device_auth_id: str,
    user_code: str,
    interval: int,
    proxy: str,
) -> DeviceLoginSession | None:
    """Record the device challenge and poll for its authorization."""
    session = _login_sessions.get(session_id)
    if session is None:
        return None
    session.status = LoginStatus.PENDING
    session.device_auth_id = device_auth_id
    session.user_code = user_code
    session.interval = interval
    session.task = asyncio.create_task(_run_device_login(session_id, proxy))
    return session


def _default_account_name(creds: dict[str, Any]) -> str:
    """Name a new account after its ChatGPT email so several stay distinct."""
    email = token_email(creds.get("access_token"))
    return email if 1 <= len(email) <= 80 else "ChatGPT"


async def _persist_login_credentials(
    creds: dict[str, Any],
    *,
    source_id: str | None = None,
    name: str = "",
    creating: bool = True,
) -> tuple[str, str]:
    """Persist only the provider bound to the server-owned device session.

    Returns the account ID and name; an empty name defaults to the email.
    """
    registry = runtime.get_coordinator().providers
    source_id = source_id or registry.new_id()
    name = name or _default_account_name(creds)
    await registry.save_login(source_id, name, creds, creating=creating)
    return source_id, name


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
            device_auth_id=session.device_auth_id or "",
            user_code=session.user_code or "",
            interval=session.interval or 5,
            proxy=proxy,
        )
        session.status = LoginStatus.SAVING
        await _persist_login_credentials(
            creds,
            source_id=session.source_id,
            name=session.name,
            creating=session.creating,
        )
        session.status = LoginStatus.SUCCESS
        logger.info("OpenAI Codex device login succeeded.")
    except asyncio.CancelledError:
        raise
    except DeviceAuthTimeout as exc:
        session.status = LoginStatus.TIMEOUT
        session.error = exc.code
    except DeviceAuthError as exc:
        session.status = LoginStatus.ERROR
        session.error = exc.code
    except Exception as exc:  # noqa: BLE001 - report a generic error without credential data
        session.status = LoginStatus.ERROR
        session.error = "login_failed"
        logger.error("OpenAI Codex device login failed: %s", type(exc).__name__)
    finally:
        if _login_sessions.get(session_id) is session:
            schedule_session_expiry(session_id, _LOGIN_RESULT_TTL_SECONDS)


async def _run_command_device_login(
    event: AstrMessageEvent,
    device_auth_id: str,
    user_code: str,
    interval: int,
    proxy: str,
) -> None:
    """Complete a private-command login without exposing credential material."""
    task = asyncio.current_task()
    try:
        creds = await _complete_device_login(
            device_auth_id=device_auth_id,
            user_code=user_code,
            interval=interval,
            proxy=proxy,
        )
        # AstrBot writes config in a worker thread; cancelling its await cannot
        # stop the write. Protect persistence and its result notification.
        if task is not None:
            _committing_command_login_tasks.add(task)
        source_id, name = await _persist_login_credentials(creds)
    except asyncio.CancelledError:
        raise
    except DeviceAuthTimeout:
        await event.send(MessageChain().message(messages.text("login.expired")))
    except DeviceAuthError as exc:
        await event.send(
            MessageChain().message(
                messages.text(
                    "login.failed", reason=messages.text(f"device.{exc.code}")
                )
            )
        )
    except Exception as exc:  # noqa: BLE001 - never send provider or credential details
        logger.error("OpenAI Codex admin device login failed: %s", type(exc).__name__)
        await event.send(MessageChain().message(messages.text("login.save_failed")))
    else:
        await event.send(
            MessageChain().message(
                messages.text("login.success", name=name, id=source_id)
            )
        )
    finally:
        if task is not None:
            _committing_command_login_tasks.discard(task)


async def _cancel_command_login(event: AstrMessageEvent, owner: str) -> None:
    task = _command_login_tasks.get(owner)
    if task is None or task.done():
        await event.send(
            MessageChain().message(messages.text("login.nothing_to_cancel"))
        )
        return
    if task in _committing_command_login_tasks:
        await event.send(MessageChain().message(messages.text("login.saving")))
        return
    _command_login_tasks.pop(owner, None)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await event.send(MessageChain().message(messages.text("login.cancelled")))


async def handle_login(event: AstrMessageEvent, action: str | None = None) -> None:
    """Add a provider through administrator-only private-chat device login.

    ``/openai_login cancel`` stops this chat's login that is still waiting.
    """
    event.should_call_llm(False)
    if not _is_private_login_event(event):
        await event.send(MessageChain().message(messages.text("login.private_only")))
        return

    owner = _command_login_owner(event)
    requested = str(action or "").strip().lower()
    if requested == "cancel":
        await _cancel_command_login(event, owner)
        return
    if requested:
        await event.send(MessageChain().message(messages.text("login.usage")))
        return
    existing_task = _command_login_tasks.get(owner)
    if existing_task is not None and not existing_task.done():
        await event.send(MessageChain().message(messages.text("login.in_progress")))
        return

    current_task = asyncio.current_task()
    if current_task is not None:
        _command_login_tasks[owner] = current_task
    try:
        proxy = runtime.get_coordinator().source_settings()["proxy"]
    except CredentialSourceError:
        proxy = ""
    try:
        try:
            device_auth_id, user_code, interval = await oauth.request_device_user_code(
                proxy
            )
        except DeviceAuthError as exc:
            await event.send(
                MessageChain().message(
                    messages.text(
                        "login.start_failed", reason=messages.text(f"device.{exc.code}")
                    )
                )
            )
            return
        except Exception as exc:  # noqa: BLE001 - keep network details out of chat
            logger.error(
                "OpenAI Codex admin device-code request failed: %s",
                type(exc).__name__,
            )
            await event.send(
                MessageChain().message(messages.text("login.start_unavailable"))
            )
            return

        await event.send(
            MessageChain().message(
                messages.text(
                    "login.instructions", url=CODEX_DEVICE_VERIFY_URL, code=user_code
                )
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
    """Cancel pending logins and wait for command logins already committing."""
    discard_all_sessions()
    tasks = _cancel_all_command_login_tasks()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
