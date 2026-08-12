"""Online watch channel providers.

See docs/CHANNEL_ARCHITECTURE.md for the role boundaries and contracts.
"""

from app.services.channels.base import ChannelError, ChannelProvider
from app.services.channels.registry import registry

__all__ = ["ChannelError", "ChannelProvider", "registry"]
