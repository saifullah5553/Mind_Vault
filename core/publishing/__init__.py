"""Platform publishing plugins. Each implements the same PlatformPublisher
interface, is credential-gated, and is only ever called for a real upload when
publishing.dry_run is false AND its credentials are present.
"""

from core.publishing.base import PlatformPublisher
from core.publishing.factory import get_publisher, publisher_status

__all__ = ["PlatformPublisher", "get_publisher", "publisher_status"]
