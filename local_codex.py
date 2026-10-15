"""Follow Codex's file-backed ChatGPT login without copying its credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .credential_store import (
    CredentialCooldownError,
    CredentialCoordinator,
    CredentialError,
    CredentialPersistenceError,
    CredentialSnapshot,
    CredentialSourceError,
    CredentialStatus,
    ReauthenticationRequiredError,
)
from .provider_registry import DEVICE, LOCAL, ProviderRegistry


def _claims(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        decoded = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return decoded if isinstance(decoded, dict) else {}
    except (ValueError, IndexError, UnicodeError):
        return {}


@dataclass(repr=False)
class LocalLogin:
    path: Path
    raw: bytes
    document: dict[str, Any]
    credentials: dict[str, Any]


class LocalCodexStore:
    """Read the active login on every lookup; only refresh writes to Codex."""

    def __init__(self, auth_path: str = "") -> None:
        self.auth_path = auth_path

    @property
    def path(self) -> Path:
        if self.auth_path:
            return Path(self.auth_path).expanduser().resolve()
        home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
        return (Path(home).expanduser() / "auth.json").resolve()

    def read(self) -> LocalLogin | None:
        try:
            path = self.path
            raw = path.read_bytes()
            document = json.loads(raw)
            if not isinstance(document, dict):
                return None
            if document.get("auth_mode") not in (None, "chatgpt"):
                return None
            if document.get("OPENAI_API_KEY"):
                return None
            tokens = document.get("tokens")
            if not isinstance(tokens, dict):
                return None
            access = tokens.get("access_token")
            if not isinstance(access, str) or not access:
                return None
            claims = _claims(access)
            expires = claims.get("exp")
            if (
                isinstance(expires, bool)
                or not isinstance(expires, (int, float))
                or not math.isfinite(expires)
            ):
                return None
            identity = claims.get("https://api.openai.com/auth")
            account = tokens.get("account_id")
            if not account and isinstance(identity, dict):
                account = identity.get("chatgpt_account_id")
            if not isinstance(account, str) or not account:
                return None
            refresh = tokens.get("refresh_token")
            return LocalLogin(
                path,
                raw,
                document,
                {
                    "access_token": access,
                    "refresh_token": refresh if isinstance(refresh, str) else "",
                    "account_id": account,
                    "expires": int(expires),
                },
            )
        except (OSError, ValueError, UnicodeError, RuntimeError):
            return None

    def write_refresh(self, login: LocalLogin, refreshed: dict[str, Any]) -> bool:
        """Replace atomically, abandoning the write if the login has changed."""
        access = refreshed.get("access_token")
        expires = _claims(access).get("exp") if isinstance(access, str) else None
        if (
            isinstance(expires, bool)
            or not isinstance(expires, (int, float))
            or not math.isfinite(expires)
            or expires <= datetime.now(UTC).timestamp()
        ):
            raise ReauthenticationRequiredError(
                "Codex returned an invalid refreshed credential."
            )
        document = {**login.document, "tokens": dict(login.document["tokens"])}
        for key in ("access_token", "refresh_token", "id_token"):
            if refreshed.get(key):
                document["tokens"][key] = refreshed[key]
        document["last_refresh"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        temporary: str | None = None
        try:
            if self.path != login.path or login.path.read_bytes() != login.raw:
                return False
            fd, temporary = tempfile.mkstemp(
                prefix=".astrbot-auth-", dir=login.path.parent
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if self.path != login.path or login.path.read_bytes() != login.raw:
                return False
            os.replace(temporary, login.path)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            raise CredentialPersistenceError(
                "Cannot save refreshed Codex credentials. Check the auth directory permissions."
            ) from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


class LocalCredentialCoordinator(CredentialCoordinator):
    """Resolve each provider through its own explicit credential source."""

    def __init__(
        self,
        *args: Any,
        local_store: LocalCodexStore | None = None,
        legacy_follow_local: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.local_store = local_store
        self.legacy_follow_local = legacy_follow_local
        self.providers = ProviderRegistry(self)
        self._identities: dict[str, tuple[str, str, str]] = {}
        self._local_cooldowns: dict[str, tuple[int | None, str]] = {}
        self._view_secret = secrets.token_bytes(32)

    def account_view(self, source_id: str | None = None) -> dict[str, Any]:
        """Return provider metadata and a revision without exposing credentials."""
        source_id = source_id or self._default_source_id
        source = self._source(source_id)
        mode = source.get("credential_mode", DEVICE)
        result = self.status(source_id).as_dict()
        result.update(
            id=source_id,
            name=source.get("name") or source_id,
            credential_mode=mode,
            credential_source="local_codex" if mode == LOCAL else "plugin",
        )
        try:
            snapshot = self._read_snapshot(source_id)
        except CredentialError:
            return result
        if snapshot.access_token:
            identity = json.dumps(
                [mode, snapshot.account_id or snapshot.access_token]
            ).encode()
            result["account_revision"] = hmac.new(
                self._view_secret, identity, hashlib.sha256
            ).hexdigest()
            claims = _claims(snapshot.access_token)
            profile = claims.get("https://api.openai.com/profile", {})
            auth = claims.get("https://api.openai.com/auth", {})
            if isinstance(profile, dict) and isinstance(profile.get("email"), str):
                result["email"] = profile["email"]
            if isinstance(auth, dict) and isinstance(
                auth.get("chatgpt_plan_type"), str
            ):
                result["plan_type"] = auth["chatgpt_plan_type"]
        return result

    async def ensure_default_source(self) -> None:
        """Migrate once and keep a local Codex provider available in the picker."""
        await self.providers.migrate()

    def credential_origin(self, source_id: str | None = None) -> str:
        """Expose the credential location without disclosing the account or tokens."""
        return self._read_snapshot(
            source_id or self._default_source_id
        ).credential_origin

    def close(self) -> None:
        super().close()
        self._identities.clear()
        self._local_cooldowns.clear()

    def _login(self, source_id: str) -> LocalLogin | None:
        if (
            self.local_store is not None
            and self._source(source_id).get("credential_mode") == LOCAL
        ):
            return self.local_store.read()
        return None

    def _read_snapshot(self, source_id: str) -> CredentialSnapshot:
        if self._source(source_id).get("credential_mode", DEVICE) not in {
            LOCAL,
            DEVICE,
        }:
            raise CredentialSourceError("Unsupported provider credential mode.")
        login = self._login(source_id)
        if login is None:
            if self._source(source_id).get("credential_mode") == LOCAL:
                snapshot = replace(
                    self._snapshot_from_source(source_id, {"key": ""}),
                    credential_origin=LOCAL,
                )
            else:
                snapshot = super()._read_snapshot(source_id)
        else:
            snapshot = self._snapshot_from_source(source_id, {"key": login.credentials})
            cooldown = self._local_cooldowns.get(snapshot.account_id, (None, None))
            snapshot = replace(
                snapshot,
                credential_origin="local_codex",
                cooldown_until=cooldown[0],
                cooldown_reason=cooldown[1],
            )
        identity = (
            snapshot.credential_origin,
            snapshot.account_id,
            snapshot.access_token,
        )
        if self._identities.get(source_id) != identity:
            self._usage_cache.pop(source_id, None)
            self._states.pop(source_id, None)
            self._identities[source_id] = identity
        return snapshot

    async def get_snapshot(
        self,
        source_id: str | None = None,
        *,
        force_refresh: bool = False,
        check_cooldown: bool = True,
        _switch_attempt: int = 0,
    ) -> CredentialSnapshot:
        source_id = source_id or self._default_source_id
        initial = self._read_snapshot(source_id)
        if initial.credential_origin == LOCAL and not initial.access_token:
            raise ReauthenticationRequiredError(
                "Sign in to local Codex on the AstrBot host."
            )
        if initial.credential_origin != "local_codex":
            return await super().get_snapshot(
                source_id, force_refresh=force_refresh, check_cooldown=check_cooldown
            )
        async with self._source_lock(source_id):
            snapshot = self._read_snapshot(source_id)
            if snapshot.credential_origin == "local_codex":
                if not snapshot.access_token:
                    raise ReauthenticationRequiredError(
                        "Sign in to local Codex on the AstrBot host."
                    )
                if check_cooldown and snapshot.is_cooling_down():
                    raise CredentialCooldownError(
                        snapshot.cooldown_until, snapshot.cooldown_reason
                    )
                force_refresh = (
                    force_refresh and initial.access_token == snapshot.access_token
                )
                if not self._needs_refresh(snapshot, force_refresh=force_refresh):
                    if snapshot.is_access_token_expired() or force_refresh:
                        self._states[source_id] = CredentialStatus("reauth_required")
                        raise ReauthenticationRequiredError(
                            "Sign in to local Codex again."
                        )
                    return snapshot
                login = self._login(source_id)
                if (
                    login is not None
                    and login.credentials["access_token"] == snapshot.access_token
                ):
                    self._states[source_id] = CredentialStatus("refreshing")
                    try:
                        refreshed = await self._refresh_credentials(
                            login.credentials,
                            self.source_settings(source_id)["proxy"] or None,
                        )
                    except Exception:  # noqa: BLE001 - never expose token endpoint errors
                        latest = self._read_snapshot(source_id)
                        if latest != snapshot:
                            pass
                        elif (
                            not snapshot.is_access_token_expired() and not force_refresh
                        ):
                            self._states[source_id] = CredentialStatus("degraded")
                            return snapshot
                        else:
                            self._states[source_id] = CredentialStatus(
                                "reauth_required"
                            )
                            raise ReauthenticationRequiredError(
                                "Sign in to local Codex again."
                            ) from None
                    else:
                        if (
                            self.local_store is not None
                            and self.local_store.write_refresh(login, refreshed)
                        ):
                            current = self._read_snapshot(source_id)
                            if (
                                current.credential_origin == "local_codex"
                                and current.access_token == refreshed["access_token"]
                            ):
                                self._states[source_id] = CredentialStatus("ready")
                                return current
        # A login changed while refreshing. Resolve again after releasing the lock.
        if _switch_attempt >= 2:
            raise CredentialSourceError(
                "The local Codex login keeps changing. Retry the request."
            )
        return await self.get_snapshot(
            source_id,
            check_cooldown=check_cooldown,
            _switch_attempt=_switch_attempt + 1,
        )

    async def mark_cooling(
        self,
        source_id: str | None,
        cooldown_until: int | None,
        *,
        reason: str = "usage_limit_reached",
        expected_access_token: str | None = None,
    ) -> CredentialSnapshot:
        source_id = source_id or self._default_source_id
        snapshot = self._read_snapshot(source_id)
        if snapshot.credential_origin != "local_codex":
            return await super().mark_cooling(
                source_id,
                cooldown_until,
                reason=reason,
                expected_access_token=expected_access_token,
            )
        if expected_access_token and expected_access_token != snapshot.access_token:
            return snapshot
        self._local_cooldowns[snapshot.account_id] = (cooldown_until, reason)
        self._usage_cache.pop(source_id, None)
        return self._read_snapshot(source_id)

    async def get_usage(
        self, source_id: str | None, fetch_usage: Any
    ) -> dict[str, Any]:
        source_id = source_id or self._default_source_id
        self._read_snapshot(source_id)

        async def fetch(snapshot: CredentialSnapshot) -> dict[str, Any]:
            result = await fetch_usage(snapshot)
            if self._read_snapshot(source_id) != snapshot:
                raise ReauthenticationRequiredError(
                    "The account changed. Retry the quota lookup."
                )
            return result

        return await super().get_usage(source_id, fetch)
