"""
ad_providers — Pluggable ad provider adapters for the Smell My City ad framework.

Usage:
    from ad_providers import get_provider
    provider = get_provider()         # uses ad_config.AD_PROVIDER
    provider = get_provider("mock")   # explicit override
"""

from ad_providers.base import AdProvider


def get_provider(name=None):
    """Return an AdProvider instance for the given provider name.

    Args:
        name: Provider name ("mock", "eltoro"). Defaults to ad_config.AD_PROVIDER.

    Returns:
        An AdProvider subclass instance.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    if name is None:
        import ad_config
        name = ad_config.AD_PROVIDER

    name = name.lower().strip()

    if name == "mock":
        from ad_providers.mock import MockAdProvider
        return MockAdProvider()
    elif name == "eltoro":
        from ad_providers.eltoro import ElToroAdProvider
        return ElToroAdProvider()
    else:
        raise ValueError(
            f"Unknown ad provider: {name!r}. "
            f"Available providers: 'mock', 'eltoro'"
        )


__all__ = ["get_provider", "AdProvider"]
