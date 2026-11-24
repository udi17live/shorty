"""Social platform connector architecture."""

from shortyy.platforms.base import (
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
from shortyy.platforms.registry import PlatformConnectorFactory
from shortyy.platforms.youtube import YouTubeConnector

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

