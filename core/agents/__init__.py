"""Agent framework: the BaseAgent class.

NOTE: the registry (`register_agent`, `get_agent`, `list_agents`) lives in
`core.registry` and is imported from there directly. It is intentionally NOT
re-exported here to avoid a circular import (registry imports BaseAgent).
"""

from core.agents.base import AgentResult, BaseAgent

__all__ = ["AgentResult", "BaseAgent"]
