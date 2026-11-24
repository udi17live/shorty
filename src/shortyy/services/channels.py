"""Connected channel and OAuth credential lifecycle service."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update

from shortyy import db
from shortyy.database import session_scope
from shortyy.models import (
    ConnectedChannel,
    OAuthCredential,
    OAuthPendingSelection,
    OAuthState,
    utcnow,
)
from shortyy.platforms.base import (
    DiscoveredChannel,
    OAuthStateError,
    OAuthTokenError,
    OAuthTokenSet,
    PlatformConnector,
    PlatformError,
    PlatformUnavailableError,
    ReauthorizationRequiredError,
    ValidCredentials,
)
from shortyy.platforms.registry import PlatformConnectorFactory
from shortyy.security import (
    EncryptionConfigError,
    EncryptionOperationError,
    constant_time_equals,
    decrypt_json,
    decrypt_secret,
    encrypt_json,
    encrypt_secret,
    generate_pkce_pair,
    generate_random_token,
    hash_token,
)
from shortyy.services.projects import ProjectError, require_project

logger = logging.getLogger(__name__)

OAUTH_STATE_TTL = timedelta(minutes=10)
PENDING_SELECTION_TTL = timedelta(minutes=10)
TOKEN_REFRESH_BUFFER = timedelta(seconds=60)


class ChannelNotFoundError(ProjectError):
    def __init__(self, message: str = "Connected channel not found") -> None:
        super().__init__(message, status_code=404)


@dataclass(frozen=True, slots=True)
class OAuthCallbackResult:
    outcome: str  # "connected" | "select" | "cancelled" | "error"
    project_id: str | None
    platform: str
    channel: dict[str, Any] | None = None
    selection_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def channel_public_dict(channel: ConnectedChannel) -> dict[str, Any]:
    """Serialize a ConnectedChannel to a frontend-safe dictionary (never includes tokens)."""
    try:
        metadata = json.loads(channel.metadata_json) if channel.metadata_json else {}
    except Exception:
        metadata = {}
    return {
        "id": channel.id,
        "project_id": channel.project_id,
        "platform": channel.platform,
        "external_account_id": channel.external_account_id,
        "external_channel_id": channel.external_channel_id,
        "display_name": channel.display_name,
        "handle": channel.handle,
        "avatar_url": channel.avatar_url,
        "status": channel.status,
        "status_message": channel.status_message,
        "metadata": metadata,
        "last_connected_at": db._dt_to_iso(channel.last_connected_at),
        "created_at": db._dt_to_iso(channel.created_at),
        "updated_at": db._dt_to_iso(channel.updated_at),
    }


def list_project_channels(project_id: str, owner_id: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)
        rows = session.scalars(
            select(ConnectedChannel)
            .where(ConnectedChannel.project_id == project_id)
            .order_by(ConnectedChannel.created_at.desc())
        ).all()
        return [channel_public_dict(c) for c in rows]


def initiate_oauth(
    project_id: str,
    platform: str,
    binding_secret: str,
    *,
    owner_id: str | None = None,
    connector: PlatformConnector | None = None,
) -> dict[str, str]:
    """Create a state + PKCE session bound to ``project_id`` and browser CSRF secret."""
    if not binding_secret:
        raise OAuthStateError("Missing browser binding secret.", code="state_mismatch")

    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)

    resolved_connector = connector or PlatformConnectorFactory.get_connector(platform)
    configured, reason = resolved_connector.is_configured()
    if not configured:
        raise PlatformError(reason or f"{platform} OAuth is not configured.", code="not_configured")

    raw_state = generate_random_token(32)
    verifier, challenge = generate_pkce_pair()
    try:
        encrypted_verifier = encrypt_secret(verifier)
    except EncryptionConfigError as exc:
        raise PlatformError(str(exc), code="not_configured") from exc

    authorization_url = resolved_connector.build_authorization_url(raw_state, challenge)
    now_ts = utcnow()
    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)
        # Clean up expired states opportunistically
        session.execute(delete(OAuthState).where(OAuthState.expires_at < now_ts))
        session.add(
            OAuthState(
                id=db.new_id(),
                state_hash=hash_token(raw_state),
                project_id=project_id,
                platform=resolved_connector.platform_id,
                owner_id=owner_id,
                binding_hash=hash_token(binding_secret),
                encrypted_pkce_verifier=encrypted_verifier,
                expires_at=now_ts + OAUTH_STATE_TTL,
                consumed_at=None,
                created_at=now_ts,
            )
        )
    return {"authorization_url": authorization_url}


def handle_oauth_callback(
    platform: str,
    *,
    code: str | None,
    state: str | None,
    error: str | None,
    binding_secret: str | None,
    owner_id: str | None = None,
    connector: PlatformConnector | None = None,
) -> OAuthCallbackResult:
    """Validate OAuth callback, exchange code, discover channels, and persist securely."""
    platform_id = platform.lower().strip()
    if not state:
        return OAuthCallbackResult(
            outcome="error",
            project_id=None,
            platform=platform_id,
            error_code="state_missing",
            error_message="Missing OAuth state parameter.",
        )

    now_ts = utcnow()
    state_digest = hash_token(state)

    with session_scope() as session:
        state_row = session.scalar(select(OAuthState).where(OAuthState.state_hash == state_digest))
        if state_row is None or state_row.platform != platform_id:
            return OAuthCallbackResult(
                outcome="error",
                project_id=None,
                platform=platform_id,
                error_code="state_mismatch",
                error_message="OAuth security verification failed. Please try connecting again.",
            )

        project_id = state_row.project_id

        if state_row.consumed_at is not None:
            return OAuthCallbackResult(
                outcome="error",
                project_id=project_id,
                platform=platform_id,
                error_code="state_reused",
                error_message="This OAuth authorization link has already been used.",
            )

        if state_row.expires_at <= now_ts:
            state_row.consumed_at = now_ts
            return OAuthCallbackResult(
                outcome="error",
                project_id=project_id,
                platform=platform_id,
                error_code="state_expired",
                error_message="OAuth authorization expired. Please try connecting again.",
            )

        if not binding_secret or not constant_time_equals(hash_token(binding_secret), state_row.binding_hash):
            logger.warning("OAuth callback rejected due to missing/mismatched CSRF browser binding")
            return OAuthCallbackResult(
                outcome="error",
                project_id=None,
                platform=platform_id,
                error_code="state_mismatch",
                error_message="OAuth security verification failed. Please start the connection from Shortyy.",
            )

        if state_row.owner_id is not None and state_row.owner_id != owner_id:
            return OAuthCallbackResult(
                outcome="error",
                project_id=None,
                platform=platform_id,
                error_code="unauthorized",
                error_message="You are not authorized to complete this connection.",
            )

        # Atomically mark state consumed to prevent replay / concurrent double-submit.
        res = session.execute(
            update(OAuthState)
            .where(OAuthState.id == state_row.id, OAuthState.consumed_at.is_(None))
            .values(consumed_at=now_ts)
        )
        if res.rowcount == 0:
            return OAuthCallbackResult(
                outcome="error",
                project_id=project_id,
                platform=platform_id,
                error_code="state_reused",
                error_message="This OAuth authorization link has already been used.",
            )

        try:
            require_project(session, project_id, owner_id=owner_id)
        except ProjectError as exc:
            return OAuthCallbackResult(
                outcome="error",
                project_id=None,
                platform=platform_id,
                error_code="invalid_project",
                error_message=str(exc),
            )

        if error:
            if error == "access_denied":
                return OAuthCallbackResult(
                    outcome="cancelled",
                    project_id=project_id,
                    platform=platform_id,
                    error_code="cancelled",
                    error_message="YouTube connection cancelled.",
                )
            logger.warning("OAuth provider returned error=%s for project=%s", error, project_id)
            return OAuthCallbackResult(
                outcome="error",
                project_id=project_id,
                platform=platform_id,
                error_code="oauth_denied",
                error_message="Authorization was not completed. Please try again.",
            )

        if not code:
            return OAuthCallbackResult(
                outcome="error",
                project_id=project_id,
                platform=platform_id,
                error_code="invalid_code",
                error_message="Authorization code missing from callback.",
            )

        try:
            code_verifier = decrypt_secret(state_row.encrypted_pkce_verifier)
        except (EncryptionConfigError, EncryptionOperationError) as exc:
            logger.error("Failed to decrypt PKCE verifier: %s", exc)
            return OAuthCallbackResult(
                outcome="error",
                project_id=project_id,
                platform=platform_id,
                error_code="server_error",
                error_message="Server encryption configuration error.",
            )

    # Perform external network calls outside the DB transaction.
    try:
        resolved_connector = connector or PlatformConnectorFactory.get_connector(platform_id)
        tokens = resolved_connector.exchange_code(code, code_verifier)
        discovered = resolved_connector.discover_channels(tokens.access_token)
    except PlatformError as exc:
        logger.warning("OAuth callback platform failure (%s): %s", exc.code, exc)
        return OAuthCallbackResult(
            outcome="error",
            project_id=project_id,
            platform=platform_id,
            error_code=exc.code,
            error_message=str(exc),
        )
    except Exception:
        logger.exception("Unexpected error during OAuth callback for project=%s", project_id)
        return OAuthCallbackResult(
            outcome="error",
            project_id=project_id,
            platform=platform_id,
            error_code="provider_unavailable",
            error_message="Could not complete YouTube connection. Please try again.",
        )

    if not discovered:
        return OAuthCallbackResult(
            outcome="error",
            project_id=project_id,
            platform=platform_id,
            error_code="no_channel",
            error_message="No YouTube channel was found on that Google account.",
        )

    if len(discovered) == 1:
        with session_scope() as session:
            require_project(session, project_id, owner_id=owner_id)
            channel = _upsert_connected_channel(
                session,
                project_id=project_id,
                platform=platform_id,
                discovered=discovered[0],
                tokens=tokens,
                owner_id=owner_id,
            )
            return OAuthCallbackResult(
                outcome="connected",
                project_id=project_id,
                platform=platform_id,
                channel=channel_public_dict(channel),
            )

    # Multiple channels returned: persist encrypted pending selection bound to the browser cookie.
    selection_id = db.new_id()
    encrypted_tokens = encrypt_json(_serialize_tokens(tokens))
    safe_candidates = [_discovered_to_dict(c) for c in discovered]
    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)
        session.execute(
            delete(OAuthPendingSelection).where(OAuthPendingSelection.expires_at < utcnow())
        )
        session.add(
            OAuthPendingSelection(
                id=selection_id,
                project_id=project_id,
                platform=platform_id,
                owner_id=owner_id,
                binding_hash=hash_token(binding_secret),
                encrypted_tokens=encrypted_tokens,
                channels_json=json.dumps(safe_candidates),
                expires_at=utcnow() + PENDING_SELECTION_TTL,
                consumed_at=None,
                created_at=utcnow(),
            )
        )
    return OAuthCallbackResult(
        outcome="select",
        project_id=project_id,
        platform=platform_id,
        selection_id=selection_id,
    )


def get_pending_selection(
    project_id: str,
    platform: str,
    selection_id: str,
    binding_secret: str | None,
    *,
    owner_id: str | None = None,
) -> dict[str, Any]:
    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)
        row = _require_valid_pending_selection(
            session, project_id, platform, selection_id, binding_secret, owner_id=owner_id
        )
        return {
            "selection_id": row.id,
            "project_id": row.project_id,
            "platform": row.platform,
            "channels": json.loads(row.channels_json),
        }


def complete_pending_selection(
    project_id: str,
    platform: str,
    selection_id: str,
    external_channel_ids: list[str],
    binding_secret: str | None,
    *,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    if not external_channel_ids:
        raise ProjectError("Select at least one channel to connect", status_code=400)

    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)
        row = _require_valid_pending_selection(
            session, project_id, platform, selection_id, binding_secret, owner_id=owner_id
        )
        candidates = {c["external_channel_id"]: c for c in json.loads(row.channels_json)}
        unknown = [cid for cid in external_channel_ids if cid not in candidates]
        if unknown:
            raise ProjectError("Invalid channel selection", status_code=400)

        tokens = _deserialize_tokens(decrypt_json(row.encrypted_tokens))
        row.consumed_at = utcnow()
        connected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cid in external_channel_ids:
            if cid in seen:
                continue
            seen.add(cid)
            cand = candidates[cid]
            discovered = DiscoveredChannel(
                external_channel_id=cand["external_channel_id"],
                external_account_id=cand.get("external_account_id"),
                display_name=cand["display_name"],
                handle=cand.get("handle"),
                avatar_url=cand.get("avatar_url"),
                metadata=cand.get("metadata") or {},
            )
            ch = _upsert_connected_channel(
                session,
                project_id=project_id,
                platform=row.platform,
                discovered=discovered,
                tokens=tokens,
                owner_id=owner_id,
            )
            connected.append(channel_public_dict(ch))
        return connected


def disconnect_channel(
    project_id: str,
    channel_id: str,
    *,
    revoke: bool = False,
    owner_id: str | None = None,
    connector: PlatformConnector | None = None,
) -> dict[str, Any]:
    """Disconnect a channel from a Project and purge stored encrypted credentials.

    By default ``revoke=False`` so disconnecting from one Shortyy Project does not
    blindly revoke the user's Google authorization for other projects.
    """
    token_to_revoke: str | None = None
    platform_id: str | None = None

    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)
        channel = session.scalar(
            select(ConnectedChannel).where(
                ConnectedChannel.id == channel_id,
                ConnectedChannel.project_id == project_id,
            )
        )
        if channel is None:
            raise ChannelNotFoundError()
        if channel.owner_id is not None and channel.owner_id != owner_id:
            raise ProjectError("You do not have access to this channel", status_code=403)

        platform_id = channel.platform
        cred = session.scalar(
            select(OAuthCredential).where(OAuthCredential.connected_channel_id == channel.id)
        )
        if cred is not None:
            if revoke:
                encrypted = cred.encrypted_refresh_token or cred.encrypted_access_token
                if encrypted:
                    try:
                        token_to_revoke = decrypt_secret(encrypted)
                    except (EncryptionConfigError, EncryptionOperationError):
                        token_to_revoke = None
            session.delete(cred)

        channel.status = "disconnected"
        channel.status_message = None
        channel.updated_at = utcnow()
        session.flush()
        result = channel_public_dict(channel)

    if revoke and token_to_revoke and platform_id:
        resolved_connector = connector or PlatformConnectorFactory.get_connector(platform_id)
        resolved_connector.revoke_token(token_to_revoke)

    return result


def remove_channel(
    project_id: str,
    channel_id: str,
    *,
    owner_id: str | None = None,
) -> None:
    """Permanently remove a channel record (and any cascading credentials) from a Project."""
    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)
        channel = session.scalar(
            select(ConnectedChannel).where(
                ConnectedChannel.id == channel_id,
                ConnectedChannel.project_id == project_id,
            )
        )
        if channel is None:
            raise ChannelNotFoundError()
        if channel.owner_id is not None and channel.owner_id != owner_id:
            raise ProjectError("You do not have access to this channel", status_code=403)
        session.delete(channel)


def get_valid_credentials(
    project_id: str,
    channel_id: str,
    *,
    owner_id: str | None = None,
    connector: PlatformConnector | None = None,
) -> ValidCredentials:
    """Return decrypted valid credentials, transparently refreshing if expired."""
    with session_scope() as session:
        require_project(session, project_id, owner_id=owner_id)
        channel = session.scalar(
            select(ConnectedChannel).where(
                ConnectedChannel.id == channel_id,
                ConnectedChannel.project_id == project_id,
            )
        )
        if channel is None:
            raise ChannelNotFoundError()
        if channel.owner_id is not None and channel.owner_id != owner_id:
            raise ProjectError("You do not have access to this channel", status_code=403)

        if channel.status == "disconnected":
            raise ReauthorizationRequiredError("This channel is disconnected. Reconnect it to continue.")

        cred = session.scalar(
            select(OAuthCredential).where(OAuthCredential.connected_channel_id == channel.id)
        )
        if cred is None or not cred.encrypted_access_token:
            channel.status = "reauthorization_required"
            channel.status_message = "Missing OAuth credentials. Please reconnect this channel."
            channel.updated_at = utcnow()
            session.commit()
            raise ReauthorizationRequiredError(channel.status_message)

        now_ts = utcnow()
        needs_refresh = (
            cred.token_expires_at is None
            or cred.token_expires_at <= now_ts + TOKEN_REFRESH_BUFFER
        )
        if not needs_refresh:
            try:
                access_token = decrypt_secret(cred.encrypted_access_token)
            except (EncryptionConfigError, EncryptionOperationError) as exc:
                raise ReauthorizationRequiredError(str(exc)) from exc
            return ValidCredentials(
                platform=channel.platform,
                external_channel_id=channel.external_channel_id,
                access_token=access_token,
                token_type=cred.token_type,
                expires_at=cred.token_expires_at,
                scopes=tuple(cred.scopes.split()) if cred.scopes else (),
            )

        if not cred.encrypted_refresh_token:
            channel.status = "reauthorization_required"
            channel.status_message = (
                "Access token expired and no refresh token is available. Reconnect required."
            )
            channel.updated_at = utcnow()
            session.commit()
            raise ReauthorizationRequiredError(channel.status_message)

        try:
            refresh_token = decrypt_secret(cred.encrypted_refresh_token)
        except (EncryptionConfigError, EncryptionOperationError) as exc:
            raise ReauthorizationRequiredError(str(exc)) from exc

        platform_id = channel.platform
        external_channel_id = channel.external_channel_id
        cred_id = cred.id

    # Call external refresh endpoint outside the session transaction.
    resolved_connector = connector or PlatformConnectorFactory.get_connector(platform_id)
    try:
        refreshed = resolved_connector.refresh_access_token(refresh_token)
    except ReauthorizationRequiredError as exc:
        with session_scope() as session:
            ch = session.get(ConnectedChannel, channel_id)
            if ch:
                ch.status = "reauthorization_required"
                ch.status_message = str(exc)
                ch.updated_at = utcnow()
        raise
    except (PlatformUnavailableError, OAuthTokenError) as exc:
        with session_scope() as session:
            ch = session.get(ConnectedChannel, channel_id)
            if ch:
                ch.status = "error" if isinstance(exc, OAuthTokenError) else "expired"
                ch.status_message = str(exc)
                ch.updated_at = utcnow()
        raise

    new_enc_access = encrypt_secret(refreshed.access_token)
    new_enc_refresh = encrypt_secret(refreshed.refresh_token) if refreshed.refresh_token else None
    with session_scope() as session:
        cred_row = session.get(OAuthCredential, cred_id)
        ch_row = session.get(ConnectedChannel, channel_id)
        if cred_row is None or ch_row is None:
            raise ChannelNotFoundError()
        cred_row.encrypted_access_token = new_enc_access
        if new_enc_refresh is not None:
            cred_row.encrypted_refresh_token = new_enc_refresh
        cred_row.token_expires_at = refreshed.expires_at
        if refreshed.scopes:
            cred_row.scopes = " ".join(refreshed.scopes)
        cred_row.updated_at = utcnow()
        ch_row.status = "connected"
        ch_row.status_message = None
        ch_row.updated_at = utcnow()
        return ValidCredentials(
            platform=platform_id,
            external_channel_id=external_channel_id,
            access_token=refreshed.access_token,
            token_type=cred_row.token_type,
            expires_at=refreshed.expires_at,
            scopes=tuple(cred_row.scopes.split()) if cred_row.scopes else (),
        )


def _require_valid_pending_selection(
    session: Any,
    project_id: str,
    platform: str,
    selection_id: str,
    binding_secret: str | None,
    *,
    owner_id: str | None = None,
) -> OAuthPendingSelection:
    row = session.scalar(
        select(OAuthPendingSelection).where(
            OAuthPendingSelection.id == selection_id,
            OAuthPendingSelection.project_id == project_id,
            OAuthPendingSelection.platform == platform.lower().strip(),
        )
    )
    if row is None or row.consumed_at is not None:
        raise ProjectError("Channel selection session was not found or already completed.", status_code=404)
    if row.expires_at <= utcnow():
        raise ProjectError("Channel selection session expired. Please connect again.", status_code=410)
    if not binding_secret or not constant_time_equals(hash_token(binding_secret), row.binding_hash):
        raise ProjectError("Channel selection session verification failed.", status_code=403)
    if row.owner_id is not None and row.owner_id != owner_id:
        raise ProjectError("You are not authorized for this channel selection.", status_code=403)
    return row


def _upsert_connected_channel(
    session: Any,
    *,
    project_id: str,
    platform: str,
    discovered: DiscoveredChannel,
    tokens: OAuthTokenSet,
    owner_id: str | None = None,
) -> ConnectedChannel:
    now_ts = utcnow()
    channel = session.scalar(
        select(ConnectedChannel).where(
            ConnectedChannel.project_id == project_id,
            ConnectedChannel.platform == platform,
            ConnectedChannel.external_channel_id == discovered.external_channel_id,
        )
    )
    if channel is None:
        channel = ConnectedChannel(
            id=db.new_id(),
            project_id=project_id,
            platform=platform,
            external_account_id=discovered.external_account_id,
            external_channel_id=discovered.external_channel_id,
            display_name=discovered.display_name,
            handle=discovered.handle,
            avatar_url=discovered.avatar_url,
            status="connected",
            status_message=None,
            metadata_json=json.dumps(discovered.metadata or {}),
            owner_id=owner_id,
            last_connected_at=now_ts,
            created_at=now_ts,
            updated_at=now_ts,
        )
        session.add(channel)
        session.flush()
    else:
        channel.external_account_id = discovered.external_account_id
        channel.display_name = discovered.display_name
        channel.handle = discovered.handle
        channel.avatar_url = discovered.avatar_url
        channel.status = "connected"
        channel.status_message = None
        channel.metadata_json = json.dumps(discovered.metadata or {})
        channel.last_connected_at = now_ts
        channel.updated_at = now_ts
        session.flush()

    enc_access = encrypt_secret(tokens.access_token)
    enc_refresh = encrypt_secret(tokens.refresh_token) if tokens.refresh_token else None
    scopes_str = " ".join(tokens.scopes)

    cred = session.scalar(
        select(OAuthCredential).where(OAuthCredential.connected_channel_id == channel.id)
    )
    if cred is None:
        cred = OAuthCredential(
            id=db.new_id(),
            connected_channel_id=channel.id,
            platform=platform,
            owner_id=owner_id,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            token_type=tokens.token_type,
            token_expires_at=tokens.expires_at,
            scopes=scopes_str,
            revoked_at=None,
            created_at=now_ts,
            updated_at=now_ts,
        )
        session.add(cred)
    else:
        cred.encrypted_access_token = enc_access
        if enc_refresh is not None:
            cred.encrypted_refresh_token = enc_refresh
        cred.token_type = tokens.token_type
        cred.token_expires_at = tokens.expires_at
        cred.scopes = scopes_str
        cred.revoked_at = None
        cred.updated_at = now_ts
    session.flush()
    return channel


def _discovered_to_dict(c: DiscoveredChannel) -> dict[str, Any]:
    return {
        "external_channel_id": c.external_channel_id,
        "external_account_id": c.external_account_id,
        "display_name": c.display_name,
        "handle": c.handle,
        "avatar_url": c.avatar_url,
        "metadata": c.metadata,
    }


def _serialize_tokens(tokens: OAuthTokenSet) -> dict[str, Any]:
    return {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
        "scopes": list(tokens.scopes),
        "token_type": tokens.token_type,
    }


def _deserialize_tokens(data: dict[str, Any]) -> OAuthTokenSet:
    exp = data.get("expires_at")
    return OAuthTokenSet(
        access_token=str(data["access_token"]),
        refresh_token=str(data["refresh_token"]) if data.get("refresh_token") else None,
        expires_at=datetime.fromisoformat(exp) if exp else None,
        scopes=tuple(data.get("scopes") or ()),
        token_type=str(data.get("token_type") or "Bearer"),
    )

