"""
CapabilityRegistry — registers and resolves IAnalyticalCapability instances.

Resolution: first registered capability that returns can_handle(context) = True.
Registration order matters: more specific capabilities first.

Usage:
  capability_registry.register(MaxValueCapability())
  cap = capability_registry.resolve(context)
  if cap:
      result = cap.execute(context, df)
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from capabilities.base import IAnalyticalCapability

if TYPE_CHECKING:
    from core.context import ExecutionContext

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Registry of all available analytical capabilities."""

    def __init__(self):
        self._capabilities: List[IAnalyticalCapability] = []

    def register(self, capability: IAnalyticalCapability) -> None:
        """Register a capability. Order matters — more specific first."""
        self._capabilities.append(capability)
        logger.debug(f"Registered capability: {capability.capability_id}")

    def resolve(self, context: "ExecutionContext") -> Optional[IAnalyticalCapability]:
        """
        Returns the first capability that can handle this context.
        Returns None if no capability matches.
        """
        for cap in self._capabilities:
            try:
                if cap.can_handle(context):
                    logger.debug(f"Capability resolved: {cap.capability_id}")
                    return cap
            except Exception as e:
                logger.warning(f"Capability {cap.capability_id}.can_handle() error: {e}")
        return None

    def list_ids(self) -> List[str]:
        """Return all registered capability IDs."""
        return [cap.capability_id for cap in self._capabilities]

    def count(self) -> int:
        return len(self._capabilities)


# ── Singleton ────────────────────────────────────────────────────────────────
capability_registry = CapabilityRegistry()
