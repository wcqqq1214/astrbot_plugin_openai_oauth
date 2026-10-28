"""Authenticated WebUI endpoints for providers, device login, and usage."""

from __future__ import annotations

import secrets
from typing import Any

from astrbot import logger
from astrbot.api.star import Context
from astrbot.api.web import json_response, request
from astrbot.core.workspace import API_KEY_USERNAME_PREFIX

from . import login, oauth, runtime
from . import usage as usage_service
from .credential_store import (
    CredentialCooldownError,
    CredentialError,
    CredentialSourceError,
    ReauthenticationRequiredError,
)
from .oauth import (
    CODEX_DEVICE_VERIFY_URL,
    DeviceAuthError,
)

_MAX_LOGIN_SESSIONS = 8
_MAX_LOGIN_SESSIONS_PER_USER = 2
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _login_request_error() -> str | None:
    owner = str(request.username or "")
    if not owner:
        return "session_identity_unavailable"
    if owner.startswith(API_KEY_USERNAME_PREFIX):
        return "api_key_not_allowed"
    return None


def _login_error_response(code: str, status_code: int):
    """Report an error as a stable code; the Plugin View translates it.

    The dashboard bridge passes only ``message`` of a failed request through.
    """
    return json_response(
        {"status": "error", "message": code},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


async def _handle_device_start() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    body = await request.json(default={}) or {}
    if not isinstance(body, dict):
        return _login_error_response("invalid_request", 400)
    coordinator = runtime.get_coordinator()
    source_id = body.get("source_id")
    creating = source_id is None
    try:
        if creating:
            name = coordinator.providers.name(body.get("name", "ChatGPT"))
            proxy = ""
        else:
            if not isinstance(source_id, str) or not source_id:
                raise CredentialSourceError(
                    "Invalid provider ID.", code="invalid_request"
                )
            source = coordinator.source(source_id)
            if source.get("credential_mode", "device_oauth") != "device_oauth":
                raise CredentialSourceError(
                    "Sign in to local Codex on the AstrBot host.",
                    code="local_login_required",
                )
            name = source.get("name") or source_id
            proxy = coordinator.source_settings(source_id)["proxy"]
    except CredentialError as exc:
        return _login_error_response(exc.code, 400)
    owner = str(request.username)
    live = login.sessions()
    for existing_id, existing in live.items():
        if existing.status not in login.ACTIVE_STATUSES:
            continue
        same_owner = secrets.compare_digest(existing.owner, owner)
        same_target = (
            creating and existing.creating and same_owner and existing.name == name
        ) or (not creating and existing.source_id == source_id)
        if not same_target:
            continue
        if same_owner:
            if existing.status != login.LoginStatus.PENDING:
                return _login_error_response("login_starting", 409)
            return json_response(
                {
                    "status": "pending",
                    "session_id": existing_id,
                    "verify_url": CODEX_DEVICE_VERIFY_URL,
                    "user_code": existing.user_code,
                    "interval": existing.interval,
                },
                headers=_NO_STORE_HEADERS,
            )
        return _login_error_response("login_in_use", 409)
    if len(live) >= _MAX_LOGIN_SESSIONS:
        return _login_error_response("login_sessions_full", 429)
    owner_sessions = sum(
        secrets.compare_digest(session.owner, owner) for session in live.values()
    )
    if owner_sessions >= _MAX_LOGIN_SESSIONS_PER_USER:
        return _login_error_response("login_sessions_full_user", 429)

    # Reserve the bounded slot before the first await so concurrent starts cannot
    # race past the quota check.
    session_id = secrets.token_urlsafe(32)
    login.reserve_session(
        session_id,
        login.DeviceLoginSession(
            owner=owner,
            source_id=coordinator.providers.new_id() if creating else source_id,
            name=name,
            creating=creating,
        ),
    )
    try:
        device_auth_id, user_code, interval = await oauth.request_device_user_code(
            proxy
        )
    except DeviceAuthError as exc:
        login.discard_session(session_id)
        return _login_error_response(exc.code, 400)
    except Exception as exc:  # noqa: BLE001 - keep network details out of the response
        login.discard_session(session_id)
        logger.error(
            "OpenAI Codex device-code request failed: %s",
            type(exc).__name__,
        )
        return _login_error_response("device_login_unavailable", 502)
    if (
        login.begin_session(
            session_id,
            device_auth_id=device_auth_id,
            user_code=user_code,
            interval=interval,
            proxy=proxy,
        )
        is None
    ):
        return _login_error_response("login_expired", 410)
    return json_response(
        {
            "status": "pending",
            "session_id": session_id,
            "verify_url": CODEX_DEVICE_VERIFY_URL,
            "user_code": user_code,
            "interval": interval,
        },
        headers=_NO_STORE_HEADERS,
    )


async def _handle_device_poll() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    body = await request.json(default={}) or {}
    if not isinstance(body, dict):
        return _login_error_response("invalid_request", 400)
    session_id = str(body.get("session_id", "") or "")
    session = login.owned_session(session_id, str(request.username))
    if session is None:
        # The WebUI bridge exposes non-2xx errors as text, not structured data.
        # Do not reveal whether an inaccessible session belongs to another user.
        return json_response({"status": "expired"}, headers=_NO_STORE_HEADERS)
    payload = {"status": str(session.status), "error": session.error}
    if session.status == login.LoginStatus.SUCCESS:
        payload["source_id"] = session.source_id
    if session.status in login.FINISHED_STATUSES:
        login.discard_session(session_id, cancel_task=False)
    return json_response(payload, headers=_NO_STORE_HEADERS)


async def _handle_device_cancel() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    body = await request.json(default={}) or {}
    if not isinstance(body, dict):
        return _login_error_response("invalid_request", 400)
    session_id = str(body.get("session_id", "") or "")
    session = login.owned_session(session_id, str(request.username))
    if session is None:
        return json_response({"status": "expired"}, headers=_NO_STORE_HEADERS)
    if session.status in {login.LoginStatus.SAVING, login.LoginStatus.SUCCESS}:
        return _login_error_response("login_saving", 409)
    login.discard_session(session_id)
    return json_response({"status": "cancelled"}, headers=_NO_STORE_HEADERS)


async def _requested_source_id() -> str:
    body = await request.json(default={}) or {}
    if not isinstance(body, dict):
        raise CredentialSourceError("Invalid request body.", code="invalid_request")
    source_id = body.get(
        "source_id",
        runtime.get_coordinator().providers.routing_view()["default_account_id"],
    )
    if not isinstance(source_id, str) or not source_id:
        raise CredentialSourceError("Invalid provider ID.", code="invalid_request")
    runtime.get_coordinator().source(source_id)
    return source_id


async def _handle_providers_list() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    try:
        coordinator = runtime.get_coordinator()
        providers = [
            coordinator.account_view(s["id"]) for s in coordinator.providers.owned()
        ]
        return json_response(
            {"providers": providers, "routing": coordinator.providers.routing_view()},
            headers=_NO_STORE_HEADERS,
        )
    except CredentialError:
        return _login_error_response("configuration_unavailable", 400)


async def _handle_routing_update() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    try:
        body = await request.json(default={}) or {}
        if (
            not isinstance(body, dict)
            or set(body) - {"account_id", "model_id"}
            or "account_id" not in body
        ):
            raise CredentialSourceError(
                "Invalid routing update.", code="invalid_request"
            )
        account_id = body["account_id"]
        model_id = body.get("model_id")
        if account_id is not None and (
            not isinstance(account_id, str) or not account_id
        ):
            raise CredentialSourceError("Invalid account ID.", code="invalid_request")
        if "model_id" in body and (not isinstance(model_id, str) or not model_id):
            raise CredentialSourceError("Invalid model ID.", code="invalid_request")
        registry = runtime.get_coordinator().providers
        await registry.update_routing(account_id, model_id=model_id)
        return json_response(
            {"status": "success", "routing": registry.routing_view()},
            headers=_NO_STORE_HEADERS,
        )
    except CredentialError as exc:
        return _login_error_response(exc.code, 400)


async def _edit_provider(*, delete: bool) -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    try:
        source_id = await _requested_source_id()
        body = await request.json(default={}) or {}
        if "source_id" not in body:
            raise CredentialSourceError(
                "Provider ID is required.", code="invalid_request"
            )
        if set(body) - {"source_id", "name", "enabled", "routing_mode"}:
            raise CredentialSourceError(
                "Unknown provider update field.", code="invalid_request"
            )
        coordinator = runtime.get_coordinator()
        await coordinator.providers.edit(
            source_id,
            delete=delete,
            **{
                key: body[key]
                for key in ("name", "enabled", "routing_mode")
                if key in body
            },
        )
        if delete:
            login.discard_sessions_for_source(source_id)
        result = {"status": "success"}
        if not delete:
            result["provider"] = coordinator.account_view(source_id)
        return json_response(result, headers=_NO_STORE_HEADERS)
    except CredentialError as exc:
        return _login_error_response(exc.code, 400)


async def _handle_provider_update() -> Any:
    return await _edit_provider(delete=False)


async def _handle_provider_delete() -> Any:
    return await _edit_provider(delete=True)


async def _handle_account_status() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    try:
        coordinator = runtime.get_coordinator()
        status = coordinator.account_view(await _requested_source_id())
    except CredentialError:
        status = {"status": "invalid"}
    return json_response(status, headers=_NO_STORE_HEADERS)


async def _handle_account_usage() -> Any:
    if message := _login_request_error():
        return _login_error_response(message, 403)
    before: dict[str, Any] = {}
    try:
        source_id = await _requested_source_id()
        coordinator = runtime.get_coordinator()
        before = coordinator.account_view(source_id)
        usage = await usage_service.fetch_source_usage(source_id)
        account = coordinator.account_view(source_id)
        if before.get("account_revision") != account.get("account_revision"):
            return json_response(
                {"status": "account_changed", "account": account},
                headers=_NO_STORE_HEADERS,
            )
    except Exception as exc:  # noqa: BLE001 - do not expose provider responses
        state = usage_service.failure_state(exc)
        if isinstance(exc, CredentialCooldownError):
            return json_response(
                {
                    "status": "cooling",
                    "cooldown_until": exc.cooldown_until,
                    "cooldown_reason": exc.reason,
                },
                headers=_NO_STORE_HEADERS,
            )
        if isinstance(exc, ReauthenticationRequiredError):
            # A login replaced while the lookup ran is not a broken login.
            account = runtime.get_coordinator().account_view(source_id)
            changed = before.get("account_revision") != account.get("account_revision")
            return json_response(
                {
                    "status": "account_changed" if changed else "reauth_required",
                    "account": account,
                },
                headers=_NO_STORE_HEADERS,
            )
        if state == "reauth_required":
            return json_response(
                {"status": "reauth_required"}, headers=_NO_STORE_HEADERS
            )
        if state is not None:
            return json_response({"status": "invalid"}, headers=_NO_STORE_HEADERS)
        logger.error("OpenAI Codex usage API failed: %s", type(exc).__name__)
        return _login_error_response("usage_failed", 502)
    return json_response(
        {"status": "success", "usage": usage, "account": account},
        headers=_NO_STORE_HEADERS,
    )


def register_routes(context: Context) -> None:
    """Register the plugin WebUI endpoints."""
    for route, handler in (
        ("providers/list", _handle_providers_list),
        ("routing/update", _handle_routing_update),
        ("providers/update", _handle_provider_update),
        ("providers/delete", _handle_provider_delete),
    ):
        context.register_web_api(
            "/astrbot_plugin_openai_oauth/" + route, handler, ["POST"], route
        )
    context.register_web_api(
        "/astrbot_plugin_openai_oauth/device/start",
        _handle_device_start,
        ["POST"],
        "开始 Codex 设备登录",
    )
    context.register_web_api(
        "/astrbot_plugin_openai_oauth/device/poll",
        _handle_device_poll,
        ["POST"],
        "查询 Codex 设备登录状态",
    )
    context.register_web_api(
        "/astrbot_plugin_openai_oauth/device/cancel",
        _handle_device_cancel,
        ["POST"],
        "取消 Codex 设备登录",
    )
    context.register_web_api(
        "/astrbot_plugin_openai_oauth/account/status",
        _handle_account_status,
        ["POST"],
        "查询 OpenAI 登录状态",
    )
    context.register_web_api(
        "/astrbot_plugin_openai_oauth/account/usage",
        _handle_account_usage,
        ["POST"],
        "查询 OpenAI 订阅额度",
    )
