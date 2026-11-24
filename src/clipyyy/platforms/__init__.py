"""Social platform connector architecture."""

from clipyyy.platforms.base import (
    ChannelDiscoveryError,
    DiscoveredChannel,
    OAuthCancelledError,
    OAuthStateError,
    OAuthTokenError,
    OAuthTokenSet,
    PlatformCapabilities,
    PlatformConfigError,
    PlatformConnector,
    PlatformError,
    PlatformMeta,
    PlatformUnavailableError,
    ReauthorizationRequiredError,
    ValidCredentials,
)
from clipyyy.platforms.registry import PlatformConnectorFactory
from clipyyy.platforms.youtube import YouTubeConnector

__all__ = [
    "ChannelDiscoveryError",
    "DiscoveredChannel",
    "OAuthCancelledError",
    "OAuthStateError",
    "OAuthTokenError",
    "OAuthTokenSet",
    "PlatformCapabilities",
    "PlatformConfigError",
    "PlatformConnector",
    "PlatformConnectorFactory",
    "PlatformError",
    "PlatformMeta",
    "PlatformUnavailableError",
    "ReauthorizationRequiredError",
    "ValidCredentials",
    "YouTubeConnector",
]

