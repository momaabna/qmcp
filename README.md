# QMCP: MCP server for QGIS

QMCP runs a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server inside QGIS Desktop, so AI assistants such as Claude Desktop, Claude Code, Cursor or VS Code can work with the project you have open:

- load, inspect and save projects and layers
- run any Processing algorithm: native, GDAL, GRASS, SAGA and plugin providers
- style layers: single symbol, categorized, graduated, raster renderers, labels and opacity
- move the map and render it to an image the assistant can look at

Everything happens in your running QGIS, so you see each change on the map as it is made.

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Connecting an MCP client](#connecting-an-mcp-client)
- [What the assistant can do](#what-the-assistant-can-do)
- [Example prompts](#example-prompts)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Further documentation](#further-documentation)

## Requirements

- QGIS 3 with Python 3.10 or newer. This is the case for QGIS 3.34 LTR and later on all platforms, which is what QMCP is tested with.
- The Python package `mcp` (1.x, version 1.8 or later). QMCP offers to install it the first time you open it, so you do not need to install it yourself.
- An MCP client, for example Claude Desktop.

## Installation

1. Copy (or symlink) the `qmcp` folder into your QGIS plugins folder:
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
2. Restart QGIS, open **Plugins → Manage and Install Plugins**, and enable **QMCP**.
3. Click the QMCP toolbar button (or **Plugins → QMCP → Model Context Protocol**).
4. The first time, QMCP checks for the `mcp` package. If it is missing, a dialog offers to install it. Click **Install**.

   The packages go into `<QGIS profile>/python/dependencies/qmcp/`, not into QGIS' own Python, so no administrator rights are needed and other plugins are not affected. If QGIS cannot load them in the same session, it asks you to restart QGIS.

## Quick start

1. Open the QMCP panel and click **Start**. The status line shows the address, by default `http://127.0.0.1:8000/mcp`.
2. Click **Set up Claude Desktop**, then fully quit and reopen Claude Desktop.
3. In a new Claude Desktop chat, ask something like *"List the layers in my QGIS project."*

Keep QGIS open with the server running while you use the assistant.

## Connecting an MCP client

The server listens on `127.0.0.1` (this computer only) and serves two endpoints:

| Endpoint | Transport | Use it for |
|---|---|---|
| `http://127.0.0.1:8000/mcp` | Streamable HTTP | Current clients |
| `http://127.0.0.1:8000/sse` | SSE (legacy) | Older clients |

The port can be changed in the panel while the server is stopped. It is remembered between sessions.

### Claude Desktop

Click **Set up Claude Desktop** in the panel. This adds a `qgis` entry to `claude_desktop_config.json` (a backup of the original file is saved next to it as `claude_desktop_config.json.bak-qmcp`). Fully quit Claude Desktop, from the tray icon or menu and not just by closing the window, then reopen it.

Claude Desktop only starts local programs, so the entry runs `mcp_bridge.py`, a small script that relays messages between Claude Desktop and the server in QGIS. It uses only the Python standard library.

### Claude Code

```bash
claude mcp add --transport http qgis http://127.0.0.1:8000/mcp
```

### Other clients (Cursor, VS Code, Windsurf, ...)

Click **Copy config for other clients**. The clipboard then holds a JSON snippet with two entries. Use whichever your client supports:

```json
{
  "mcpServers": {
    "qgis": {
      "command": "/usr/bin/python3",
      "args": ["/path/to/qmcp/mcp_bridge.py", "http://127.0.0.1:8000/mcp"]
    },
    "qgis-http": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

- `qgis` is for clients that start a local program (stdio).
- `qgis-http` is for clients that connect to a URL.

### After updating QMCP

Clients read the tool list once, when they connect. After updating or reloading the plugin, restart the server in QGIS, then restart the client and start a new chat. Otherwise the assistant keeps using the old tool names and parameters.

## What the assistant can do

The server offers 29 tools. [docs/tools.md](docs/tools.md) describes each one with its parameters and examples.

| Area | Tools |
|---|---|
| General | `ping`, `get_qgis_info` |
| Project | `get_project_info`, `load_project`, `create_new_project`, `save_project` |
| Layers | `get_layers`, `add_vector_layer`, `add_raster_layer`, `remove_layer`, `rename_layer`, `set_layer_visibility`, `zoom_to_layer`, `get_layer_features` |
| Processing | `search_algorithms`, `get_algorithm_help`, `run_algorithm` |
| Styling | `get_layer_style`, `set_layer_style`, `set_layer_opacity`, `set_categorized_style`, `set_graduated_style`, `set_raster_style`, `set_layer_labels`, `save_layer_style`, `load_layer_style` |
| Map | `set_map_extent`, `render_map` |
| Scripting | `execute_code` |

Some conventions apply to all tools:

- **Layers** are given by layer ID or by name. If two layers have the same name, the tool asks for the ID instead of guessing.
- **Colours** are `"#RRGGBB"`, `"#RRGGBBAA"` or `"r,g,b,a"`. Opacity is a number from 0 to 1.
- **Processing** uses three tools instead of one per algorithm. The assistant searches for an algorithm, reads its parameters, then runs it. This covers every provider installed in your QGIS, including plugins, without flooding the assistant with hundreds of tool definitions.
- **Errors are explicit.** Unknown parameters, bad colours or a parameter that does not fit the layer type are rejected with a message that says what to use instead, and nothing is changed.

## Example prompts

- *"Add `/data/riyadh/buildings.gpkg`, colour the buildings by their `use` field, and show me the map."*
- *"Buffer the roads layer by 50 m and dissolve the result."*
- *"Make the Riyadh bounding box transparent with a red outline."*
- *"Style the DEM with the Viridis ramp between 500 and 900 m, at 60% opacity."*
- *"Zoom to 30 km around 24.71 N, 46.67 E."*
- *"Label the districts with their names, 10 pt with a white halo."*
- *"Save this style to `/data/styles/districts.qml` and apply it to the other district layers."*

## Security

- The server only listens on `127.0.0.1`, so other computers cannot reach it. Any program on your own computer can, though, while the server is running. Stop the server when you are not using it.
- The server has no authentication.
- `execute_code` runs arbitrary Python inside QGIS, with full access to your files. Other tools cover most tasks, so if your client supports it, disable `execute_code` or require confirmation before each call.
- Tools can overwrite files (`save_project`, `save_layer_style`, `render_map` with a path, and Processing outputs) and change the open project. Save your work first.

## Troubleshooting

**The panel says the port is already in use.**
Another program, or a second QGIS window, is using the port. Pick another port in the panel. Then click **Set up Claude Desktop** again (or copy the config again), because the address changed.

**The client says QGIS is not reachable.**
QGIS is closed or the server is stopped. Open the QMCP panel and click **Start**.

**The assistant uses tools or parameters that do not exist, such as `execute_processing` or `layer_id`.**
The client still has the tool list from an older version. Restart the client completely and start a new chat. Unknown parameters are rejected with a message naming them, for example `layer_id: Extra inputs are not permitted`.

**The QMCP tools do not appear in Claude Desktop.**
Check that `claude_desktop_config.json` contains the `qgis` entry, then fully quit and reopen Claude Desktop. Its log is at `~/.config/Claude/logs/mcp-server-qgis.log` on Linux, `~/Library/Logs/Claude/` on macOS and `%APPDATA%\Claude\logs\` on Windows.

**Installing the dependencies fails.**
The dialog shows pip's output. On Debian and Ubuntu, QGIS' Python may lack pip: install it with `sudo apt install python3-pip` and try again. You can also install manually with QGIS' Python:
`python3 -m pip install --target "<QGIS profile>/python/dependencies/qmcp/py3XX" "mcp>=1.8,<2"`

**QGIS is unresponsive while the assistant works.**
Tools run on QGIS' main thread, because QGIS requires that for anything that touches the project or the map. A long Processing algorithm therefore blocks the QGIS window until it finishes.

## Further documentation

- [docs/tools.md](docs/tools.md): every tool, its parameters, what it returns and its errors.
- [docs/development.md](docs/development.md): how the plugin works, how to add a tool, and how to test and package it.

## License

GNU General Public License v2 or later. © 2025 Mohammed Nasser.
