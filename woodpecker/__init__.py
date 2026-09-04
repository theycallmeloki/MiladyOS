"""MiladyOS CI package: forgejo/woodpecker plumbing + the MiladyCI facade.

`woodpecker_client.WoodpeckerClient` is the thin, verified REST client for the
local forgejo/woodpecker stack (repos, files, activation, triggering,
status/logs). `service.MiladyCI` is the high-level facade milady and the MCP
tools talk to — it owns the forge/woodpecker machinery so a caller only ever
names a logical *job* + variables.
"""
from .woodpecker_client import WoodpeckerClient
from .service import MiladyCI, KNOWN_JOBS

__all__ = ["WoodpeckerClient", "MiladyCI", "KNOWN_JOBS"]
