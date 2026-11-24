"""YouTube OAuth 2.0 and YouTube Data API v3 connector."""

from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlencode, urlparse

import httpx

from clipyyy.config import get_google_oauth_config
from clipyyy.models import utcnow
from clipyyy.platforms.base import (
    ChannelDiscoveryError,
    DiscoveredChannel,
    OAuthTokenError,
    OAuthTokenSet,
    PlatformCapabilities,
    PlatformConfigError,
    PlatformConnector,
    PlatformMeta,
    PlatformUnavailableError,
    ReauthorizationRequiredError,
)
from clipyyy.security import validate_encryption_key

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

# Minimum scope needed for channel discovery & connection verification (no upload/write scopes yet).
YOUTUBE_CONNECT_SCOPES = ("https://www.googleapis.com/auth/youtube.readonly",)


class YouTubeConnector(PlatformConnector):
    """Connector for YouTube channels via Google OAuth 2.0."""

    platform_id = "youtube"
    meta = PlatformMeta(
        id="youtube",
        name="YouTube",
        description="Connect your YouTube channel via Google OAuth 2.0",
        status="available",
        capabilities=PlatformCapabilities(supports_oauth=True, supports_multi_channel=True),
    )

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        cfg_id, cfg_secret, cfg_redirect = get_google_oauth_config()
        self._client_id = client_id if client_id is not None else cfg_id
        self._client_secret = client_secret if client_secret is not None else cfg_secret
        self._redirect_uri = redirect_uri if redirect_uri is not None else cfg_redirect
        self._transport = transport
        self._timeout = timeout

    def _http_client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, transport=self._transport)

    def _validate_redirect_uri(self, uri: str) -> bool:
        if not uri:
            return False
        parsed = urlparse(uri)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def is_configured(self) -> tuple[bool, str | None]:
        if not self._client_id or not self._client_secret:
            return (
                False,
                "Google OAuth credentials (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET) are not configured.",
            )
        if not self._validate_redirect_uri(self._redirect_uri):
            return False, "GOOGLE_OAUTH_REDIRECT_URI must be a valid http(s) URL."
        enc_ok, enc_msg = validate_encryption_key()
        if not enc_ok:
            return False, enc_msg
        return True, None

    def _require_configured(self) -> None:
        ok, reason = self.is_configured()
        if not ok:
            raise PlatformConfigError(reason or "YouTube OAuth is not configured.")

    def build_authorization_url(self, state: str, code_challenge: str) -> str:
        self._require_configured()
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(YOUTUBE_CONNECT_SCOPES),
            "access_type": "offline",
            "prompt": "select_account consent",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> OAuthTokenSet:
        self._require_configured()
        if not code:
            raise OAuthTokenError("Missing authorization code from Google.")
        try:
            with self._http_client() as client:
                response = client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "code": code,
                        "code_verifier": code_verifier,
                        "redirect_uri": self._redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("Google OAuth token exchange network error: %s", exc)
            raise PlatformUnavailableError(
                "Could not reach Google OAuth service. Please try again."
            ) from exc

        if response.status_code >= 500:
            logger.warning("Google OAuth token endpoint returned %s", response.status_code)
            raise PlatformUnavailableError(
                "Google OAuth service is temporarily unavailable. Please try again."
            )

        payload = _safe_json(response)
        if response.status_code >= 400:
            err_code = str(payload.get("error") or "oauth_error")
            logger.warning(
                "Google OAuth token exchange failed (status=%s, error=%s)",
                response.status_code,
                err_code,
            )
            if err_code == "invalid_grant":
                raise OAuthTokenError(
                    "Authorization code is invalid or expired. Please try connecting again."
                )
            if err_code == "redirect_uri_mismatch":
                raise PlatformConfigError(
                    "Google OAuth redirect URI mismatch. Verify GOOGLE_OAUTH_REDIRECT_URI configuration."
                )
            raise OAuthTokenError("Google OAuth authorization failed. Please try again.")

        access_token = payload.get("access_token")
        if not access_token:
            logger.warning("Google OAuth token response missing access_token")
            raise OAuthTokenError("Google did not return an access token.")

        expires_in = payload.get("expires_in")
        expires_at = (
            utcnow() + timedelta(seconds=max(0, int(expires_in)))
            if expires_in is not None
            else None
        )
        scopes = tuple(str(payload.get("scope") or "").split()) or YOUTUBE_CONNECT_SCOPES
        return OAuthTokenSet(
            access_token=str(access_token),
            refresh_token=str(payload["refresh_token"]) if payload.get("refresh_token") else None,
            expires_at=expires_at,
            scopes=scopes,
            token_type=str(payload.get("token_type") or "Bearer"),
        )

    def discover_channels(self, access_token: str) -> list[DiscoveredChannel]:
        try:
            with self._http_client() as client:
                response = client.get(
                    YOUTUBE_CHANNELS_URL,
                    params={"part": "snippet", "mine": "true", "maxResults": "50"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("YouTube channel discovery network error: %s", exc)
            raise PlatformUnavailableError(
                "Could not reach YouTube API. Please try again."
            ) from exc

        if response.status_code >= 500:
            logger.warning("YouTube channels API returned %s", response.status_code)
            raise PlatformUnavailableError(
                "YouTube API is temporarily unavailable. Please try again."
            )

        payload = _safe_json(response)
        if response.status_code == 401:
            raise OAuthTokenError("Google authorization token was rejected by YouTube.")
        if response.status_code >= 400:
            reason = _extract_google_error_reason(payload)
            logger.warning(
                "YouTube channels API error (status=%s, reason=%s)",
                response.status_code,
                reason,
            )
            raise ChannelDiscoveryError(
                "Could not retrieve YouTube channel details from Google. "
                "Verify YouTube Data API v3 is enabled and try again.",
                code="discovery_failed",
            )

        items = payload.get("items") or []
        channels: list[DiscoveredChannel] = []
        for item in items:
            channel_id = str(item.get("id") or "").strip()
            if not channel_id:
                continue
            snippet = item.get("snippet") or {}
            title = str(snippet.get("title") or channel_id).strip()
            custom_url = str(snippet.get("customUrl") or "").strip() or None
            if custom_url and not custom_url.startswith("@") and "/" not in custom_url:
                custom_url = f"@{custom_url}"
            thumbnails = snippet.get("thumbnails") or {}
            avatar_url = None
            for size_key in ("high", "medium", "default"):
                thumb = thumbnails.get(size_key) or {}
                if thumb.get("url"):
                    avatar_url = str(thumb["url"])
                    break
            metadata = {
                "description": str(snippet.get("description") or "")[:500],
                "country": snippet.get("country"),
                "published_at": snippet.get("publishedAt"),
            }
            channels.append(
                DiscoveredChannel(
                    external_channel_id=channel_id,
                    external_account_id=None,
                    display_name=title,
                    handle=custom_url,
                    avatar_url=avatar_url,
                    metadata=metadata,
                )
            )
        return channels

    def refresh_access_token(self, refresh_token: str) -> OAuthTokenSet:
        self._require_configured()
        if not refresh_token:
            raise ReauthorizationRequiredError("Missing refresh token. Please reconnect YouTube.")
        try:
            with self._http_client() as client:
                response = client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("Google OAuth token refresh network error: %s", exc)
            raise PlatformUnavailableError(
                "Could not reach Google OAuth service to refresh token."
            ) from exc

        if response.status_code >= 500:
            logger.warning("Google OAuth token refresh returned %s", response.status_code)
            raise PlatformUnavailableError("Google OAuth service is temporarily unavailable.")

        payload = _safe_json(response)
        if response.status_code >= 400:
            err_code = str(payload.get("error") or "refresh_failed")
            logger.warning(
                "Google OAuth token refresh failed (status=%s, error=%s)",
                response.status_code,
                err_code,
            )
            if err_code in {"invalid_grant", "unauthorized_client"} or response.status_code == 401:
                raise ReauthorizationRequiredError(
                    "YouTube authorization expired or was revoked. Please reconnect this channel."
                )
            raise OAuthTokenError("Failed to refresh YouTube access token.", code="token_refresh_failed")

        access_token = payload.get("access_token")
        if not access_token:
            raise OAuthTokenError("Google token refresh did not return an access token.")

        expires_in = payload.get("expires_in")
        expires_at = (
            utcnow() + timedelta(seconds=max(0, int(expires_in)))
            if expires_in is not None
            else None
        )
        scopes = tuple(str(payload.get("scope") or "").split())
        return OAuthTokenSet(
            access_token=str(access_token),
            refresh_token=str(payload["refresh_token"]) if payload.get("refresh_token") else None,
            expires_at=expires_at,
            scopes=scopes,
            token_type=str(payload.get("token_type") or "Bearer"),
        )

    def revoke_token(self, token: str) -> bool:
        if not token:
            return False
        try:
            with self._http_client() as client:
                response = client.post(GOOGLE_REVOKE_URL, params={"token": token})
            return response.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("Google OAuth token revocation failed: %s", exc)
            return False


def _safe_json(response: httpx.Response) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_google_error_reason(payload: dict) -> str:
    err = payload.get("error")
    if isinstance(err, dict):
        errors = err.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            return str(errors[0].get("reason") or err.get("status") or "unknown")
        return str(err.get("status") or err.get("message") or "unknown")
    return str(err or "unknown")

