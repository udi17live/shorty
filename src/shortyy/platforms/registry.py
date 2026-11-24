"""Platform connector factory and registry."""

from __future__ import annotations

from typing import Any

from shortyy.platforms.base import (
    PlatformCapabilities,
    PlatformConnector,
    PlatformError,
    PlatformMeta,
)
from shortyy.platforms.youtube import YouTubeConnector

# Future platforms declared for UI registry visibility without fake OAuth implementations.
FUTURE_PLATFORMS: tuple[PlatformMeta, ...] = (
    PlatformMeta(
        id="tiktok",
        name="TikTok",
        description="Connect your TikTok account",
        status="coming_soon",
        capabilities=PlatformCapabilities(supports_oauth=False, supports_multi_channel=False),
    ),
    PlatformMeta(
        id="instagram",
        name="Instagram",
        description="Connect an Instagram professional account",
        status="coming_soon",
        capabilities=PlatformCapabilities(supports_oauth=False, supports_multi_channel=False),
    ),
    PlatformMeta(
        id="facebook",
        name="Facebook",
        description="Connect a Facebook Page",
        status="coming_soon",
        capabilities=PlatformCapabilities(supports_oauth=False, supports_multi_channel=True),
    ),
    PlatformMeta(
        id="x",
        name="X",
        description="Connect your X account",
        status="coming_soon",
        capabilities=PlatformCapabilities(supports_oauth=False, supports_multi_channel=False),
    ),
)


class PlatformConnectorFactory:
    """Registry and factory for social platform connectors."""

    _registry: dict[str, type[PlatformConnector]] = {
        "youtube": YouTubeConnector,
    }

    @classmethod
    def register(cls, platform: str, connector_cls: type[PlatformConnector]) -> None:
        cls._registry[platform.lower().strip()] = connector_cls

    @classmethod
    def get_connector(cls, platform: str, **kwargs: Any) -> PlatformConnector:
        key = platform.lower().strip()
        connector_cls = cls._registry.get(key)
        if connector_cls is None:
            raise PlatformError(f"Platform '{platform}' is not supported yet.", code="unsupported_platform")
        return connector_cls(**kwargs)

    @classmethod
    def supported_platforms(cls) -> list[str]:
        return sorted(cls._registry.keys())

    @classmethod
    def list_platforms(cls) -> list[dict[str, Any]]:
        """Return safe metadata for active and upcoming platforms."""
        items: list[dict[str, Any]] = []
        for key in sorted(cls._registry.keys()):
            connector = cls.get_connector(key)
            configured, config_error = connector.is_configured()
            meta = connector.meta
            items.append(
                {
                    "id": meta.id,
                    "name": meta.name,
                    "description": meta.description,
                    "status": meta.status,
                    "configured": configured,
                    "config_error": config_error,
                    "supports_oauth": meta.capabilities.supports_oauth,
                    "supports_multi_channel": meta.capabilities.supports_multi_channel,
                }
            )
        for meta in FUTURE_PLATFORMS:
            if meta.id in cls._registry:
                continue
            items.append(
                {
                    "id": meta.id,
                    "name": meta.name,
                    "description": meta.description,
                    "status": meta.status,
                    "configured": False,
                    "config_error": None,
                    "supports_oauth": meta.capabilities.supports_oauth,
                    "supports_multi_channel": meta.capabilities.supports_multi_channel,
                }
            )
        return items

