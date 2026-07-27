"""Agent registry.

DESIGN: A decorator-based registry decouples the orchestrator from concrete
agent classes. Agents register themselves under a stable key; the orchestrator
and API look them up by name. This is what lets you add a new agent (or a whole
new content category's specialist) without editing the orchestrator.
"""

from __future__ import annotations

from typing import Callable, Type

from core.agents.base import BaseAgent

_REGISTRY: dict[str, Type[BaseAgent]] = {}


def register_agent(cls: Type[BaseAgent]) -> Type[BaseAgent]:
    """Class decorator: `@register_agent` registers under `cls.name`."""
    key = cls.name
    if key in _REGISTRY and _REGISTRY[key] is not cls:
        raise ValueError(f"Agent name collision: {key!r}")
    _REGISTRY[key] = cls
    return cls


def get_agent(name: str) -> BaseAgent:
    if name not in _REGISTRY:
        raise KeyError(f"No agent registered as {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def list_agents() -> list[str]:
    return sorted(_REGISTRY)


def load_all_agents() -> None:
    """Import the agents package so every @register_agent runs. Import-safe."""
    import importlib
    import pkgutil

    import agents as agents_pkg

    for mod in pkgutil.walk_packages(agents_pkg.__path__, prefix="agents."):
        if mod.name.endswith(".agent"):
            importlib.import_module(mod.name)
