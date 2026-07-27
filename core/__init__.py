"""Mind_Vault — shared framework package.

`core` holds every piece of infrastructure the agents rely on: configuration,
logging, database, the pluggable LLM / TTS / image / video layers, schemas,
duplicate detection, the BaseAgent class, the agent registry, and the
orchestrator. Agents in the top-level `agents/` package import from here rather
than re-implementing infrastructure, so there is exactly one place to fix a bug
or swap a provider.
"""

__version__ = "0.1.0"
