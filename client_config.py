# -*- coding: utf-8 -*-
"""
Connection settings for MCP clients (Claude Desktop, Cursor, VS Code, ...).

Clients that support HTTP connect to the server URL directly. Clients that
only launch local processes run mcp_bridge.py with QGIS' own Python.
"""

import glob
import json
import os
import shutil
import sys

from .dependencies import python_executable

SERVER_NAME = "qgis"
BRIDGE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_bridge.py")


def bridge_python():
    """Python used to run the bridge; any Python 3 works since it is stdlib-only."""
    python = python_executable()
    if python:
        return python
    return shutil.which("python3") or shutil.which("python") or "python3"


def stdio_server_entry(url):
    return {"command": bridge_python(), "args": [BRIDGE_SCRIPT, url]}


def client_config_json(url):
    """Config snippet for clients, covering both stdio and HTTP styles."""
    return json.dumps({
        "mcpServers": {
            SERVER_NAME: stdio_server_entry(url),
            SERVER_NAME + "-http": {"type": "http", "url": url},
        }
    }, indent=2)


def claude_desktop_config_paths():
    """Candidate claude_desktop_config.json locations for this OS."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        paths = [os.path.join(appdata, "Claude", "claude_desktop_config.json")]
        # The Microsoft Store build reads a virtualised copy of %APPDATA%
        local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        for package in glob.glob(os.path.join(local, "Packages", "Claude_*")):
            paths.append(os.path.join(package, "LocalCache", "Roaming", "Claude",
                                      "claude_desktop_config.json"))
        return paths
    if sys.platform == "darwin":
        return [os.path.join(home, "Library", "Application Support", "Claude",
                             "claude_desktop_config.json")]
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return [os.path.join(config_home, "Claude", "claude_desktop_config.json")]


def install_claude_desktop(url):
    """Add or update the QGIS server in Claude Desktop's config.

    Returns the list of files written. Raises ValueError if an existing
    config file is not valid JSON (it is left untouched).
    """
    written = []
    for path in claude_desktop_config_paths():
        config = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if text.strip():
                try:
                    config = json.loads(text)
                except ValueError as e:
                    raise ValueError("{} is not valid JSON: {}".format(path, e))
            backup = path + ".bak-qmcp"
            if not os.path.exists(backup):
                shutil.copy2(path, backup)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)

        config.setdefault("mcpServers", {})[SERVER_NAME] = stdio_server_entry(url)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        written.append(path)
    return written
