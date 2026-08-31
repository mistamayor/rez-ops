"""Unit tests for `.mcp.json`'s actual shape (Story 11 review fix).

The story's own Acceptance Criterion -- "it registers all five servers
(`ledger-core`, `git-repo`, `ticketing`, `calendar-google`, `cmdb`) and none
are given a config-file-sourced credential" -- was previously checked only
by a manual command in the spec's Verification section, never by
`uv run pytest`. This module closes that gap.
"""

from __future__ import annotations

import json
from pathlib import Path

_MCP_CONFIG_PATH = Path(__file__).resolve().parent.parent / ".mcp.json"

#: Expected server -> module mapping, per the story's Intent ("each launched
#: as `uv run python -m {module}.server`, per their existing entry points").
_EXPECTED_SERVERS = {
    "ledger-core": "ledger_core.server",
    "git-repo": "connectors.git_repo.server",
    "ticketing": "connectors.ticketing.server",
    "calendar-google": "connectors.calendar_google.server",
    "cmdb": "connectors.cmdb.server",
}


def _load_config() -> dict:
    with _MCP_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_mcp_config_is_valid_json() -> None:
    config = _load_config()
    assert isinstance(config, dict)


def test_mcp_config_registers_exactly_the_five_expected_servers() -> None:
    config = _load_config()
    servers = config["mcpServers"]
    assert set(servers.keys()) == set(_EXPECTED_SERVERS.keys())


def test_mcp_config_servers_have_expected_command_and_args() -> None:
    config = _load_config()
    servers = config["mcpServers"]

    for name, module in _EXPECTED_SERVERS.items():
        entry = servers[name]
        assert entry["command"] == "uv"
        assert entry["args"] == ["run", "python", "-m", module]


def test_mcp_config_servers_have_no_credential_shaped_fields() -> None:
    # AD-7: credentials come only from the OS keychain/env, never a
    # git-tracked file -- so no server entry may carry an `env` block (or
    # any other credential-shaped key) that could hold a secret in-repo.
    credential_shaped_keys = {"env", "credentials", "token", "apiKey", "api_key", "secret"}
    config = _load_config()
    servers = config["mcpServers"]

    for name, entry in servers.items():
        found = credential_shaped_keys & set(entry.keys())
        assert not found, f"server {name!r} has credential-shaped key(s): {found}"
        # And no field's value contains anything cred-like by heuristic.
        assert set(entry.keys()) <= {"command", "args"}, (
            f"server {name!r} has unexpected key(s): "
            f"{set(entry.keys()) - {'command', 'args'}}"
        )
