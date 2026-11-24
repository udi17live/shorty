"""Platform connector interfaces, domain exceptions, and shared data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


class PlatformError(RuntimeError):
    """Base error for platform connector operations with user-safe message."""

    def __init__(self, message: str, *, code: str = "platform_error") -> None:
        super().__init__(message)
        self.code = code


class PlatformConfigError(PlatformError):
    """Raised when required OAuth/encryption configuration is missing or invalid."""

    def __init__(self, message: str, *, code: str = "not_configured") -> None:
        super().__init__(message, code=code)


class OAuthCancelledError(PlatformError):
    """Raised when the user cancels OAuth consent on the provider side."""

    def __init__(self, message: str = "Connection cancelled.", *, code: str = "cancelled") -> None:
        super().__init__(message, code=code)


class OAuthStateError(PlatformError):
    """Raised when OAuth state or CSRF browser binding validation fails."""

    def __init__(self, message: str, *, code: str = "state_mismatch") -> None:
        super().__init__(message, code=code)


class OAuthTokenError(PlatformError):
    """Raised when exchanging or validating OAuth tokens fails."""

    def __init__(self, message: str, *, code: str = "exchange_failed") -> None:
        super().__init__(message, code=code)


class ChannelDiscoveryError(PlatformError):
    """Raised when discovering channels for an authorized account fails or finds none."""

    def __init__(self, message: str, *, code: str = "no_channel") -> None:
        super().__init__(message, code=code)


class PlatformUnavailableError(PlatformError):
    """Raised when an external platform API is unreachable or returning 5xx errors."""

    def __init__(self, message: str, *, code: str = "provider_unavailable") -> None:
        super().__init__(message, code=code)


class ReauthorizationRequiredError(PlatformError):
    """Raised when stored credentials cannot be refreshed and user must reconnect."""

    def __init__(self, message: str, *, code: str = "reauthorization_required") -> None:
        super().__init__(message, code=code)


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    supports_oauth: bool = True
    supports_multi_channel: bool = True


@dataclass(frozen=True, slots=True)
class PlatformMeta:
    id: str
    name: str
    description: str
    status: Literal["available", "coming_soon"]
    capabilities: PlatformCapabilities = field(default_factory=PlatformCapabilities)


@dataclass(frozen=True, slots=True)
class DiscoveredChannel:
    external_channel_id: str
    display_name: str
    external_account_id: str | None = None
    handle: str | None = None
    avatar_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OAuthTokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()
    token_type: str = "Bearer"


@dataclass(frozen=True, slots=True)
class ValidCredentials:
    """Internal backend-only credential bundle for future publishing connectors.

    Never serialize or return this object to frontend HTTP responses.
    """

    platform: str
    external_channel_id: str
    access_token: str
    token_type: str
    expires_at: datetime | None
    scopes: tuple[str, ...]


class PlatformConnector(ABC):
    """Abstract connector implemented by each social platform integration."""

    platform_id: str
    meta: PlatformMeta

    @abstractmethod
    def is_configured(self) -> tuple[bool, str | None]:
        """Return ``(configured, safe_reason_if_not)``."""

    @abstractmethod
    def build_authorization_url(self, state: str, code_challenge: str) -> str:
        """Build the provider's OAuth 2.0 authorization URL."""

    @abstractmethod
    def exchange_code(self, code: str, code_verifier: str) -> OAuthTokenSet:
        """Exchange an authorization code + PKCE verifier for OAuth tokens."""

    @abstractmethod
    def discover_channels(self, access_token: str) -> list[DiscoveredChannel]:
        """Discover the channels/accounts accessible under ``access_token``."""

    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> OAuthTokenSet:
        """Refresh an expired access token using a refresh token."""

    @abstractmethod
    def revoke_token(self, token: str) -> bool:
        """Explicitly revoke an OAuth token with the provider."""

