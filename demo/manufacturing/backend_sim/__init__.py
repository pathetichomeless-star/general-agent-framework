"""Backend factory for the public simulated backend.

    from framework_port.dtos import BackendConfig
    from backend_sim import create_backend
    backend = create_backend(BackendConfig(db_path=...))

The simulated backend is deterministic, in-process and synthetic-data only.
It never contacts an external system and never claims to be a licensed
framework runtime.
"""

from __future__ import annotations

from framework_port.dtos import BackendConfig

from .engine import PublicSimulatedBackend

__all__ = ["PublicSimulatedBackend", "create_backend"]


def create_backend(config: BackendConfig) -> PublicSimulatedBackend:
    return PublicSimulatedBackend(config)
