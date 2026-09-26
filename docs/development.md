# QMCP developer guide

This guide explains how QMCP works inside QGIS, how to add a tool, and how to test and package the plugin. For end-user documentation see the [README](../README.md). For the tools themselves see [tools.md](tools.md).

## Architecture

```
 MCP client (Claude Desktop, Cursor, …)
      │  stdio                          ┌──────────────────── QGIS process ───────────────────┐
      ▼                                 │                                                      │
 mcp_bridge.py  ── HTTP POST /mcp ────▶ │  uvicorn (background thread "qmcp-server")          │
                                        │     └─ FastMCP app: streamable HTTP /mcp + SSE /sse │
 HTTP clients (Claude Code, …) ───────▶ │           │ tool call                                │
                                        │           ▼                                          │
                                        │  _MainThreadInvoker ─ queued Qt signal ─▶ GUI thread │
                                        │           ▲                     runs the tool,       │
                                        │           └──── Future ◀────── touches QgsProject    │
                                        └──────────────────────────────────────────────────────┘
```

- **The server runs inside QGIS.** A uvicorn server runs on a daemon thread and serves the FastMCP app. Tools can therefore use `QgsProject.instance()`, `iface` and `processing` directly, with no second process.
- **Tools run on the GUI thread.** QGIS objects must only be used from the main thread. `MainThreadFastMCP` wraps every tool so that calling it emits a queued Qt signal. The GUI thread runs the function and fills a `concurrent.futures.Future`, which the server thread awaits. Tool code is therefore ordinary synchronous PyQGIS. The cost is that a long tool, such as a slow Processing algorithm, blocks the QGIS window while it runs.
- **Stateless HTTP.** The server is created with `stateless_http=True, json_response=True`. There are no sessions, so clients and the bridge keep working after the server is restarted. The downside is that clients are never told when the tool list changes; they need to reconnect.
- **The bridge.** `mcp_bridge.py` uses only the standard library, so any Python 3 can run it. It reads JSON-RPC messages from stdin, POSTs each one to the server on its own thread (so a long call doesn't block others), and writes the replies to stdout. If QGIS can't be reached, it answers each request with an error that tells the user to start the server.

## Files

| File | Purpose |
|---|---|
| `__init__.py` | QGIS entry point (`classFactory`) |
| `qmcp.py` | Plugin class: toolbar action, dependency check, creates the dock widget, stops the server on unload |
| `qmcp_dockwidget.py`, `qmcp_dockwidget_base.ui` | The panel: Start/Stop, port, client setup buttons |
| `mcp_runtime.py` | `MainThreadFastMCP` (main-thread dispatch, rejects unknown arguments) and `MCPServerController` (starts and stops uvicorn, reports its state to the panel) |
| `mcp_tools.py` | Creates `mcp_server` and defines the project, layer, Processing, render and `execute_code` tools, plus shared helpers |
| `style_tools.py` | Styling, labelling, layer tree and map extent tools. Imported at the end of `mcp_tools.py`, which registers them. |
| `mcp_bridge.py` | stdio to HTTP relay for clients that only start local programs |
| `client_config.py` | Builds client config snippets and writes Claude Desktop's config |
| `dependencies.py` | Checks for `mcp` and `uvicorn` and installs them with `pip --target` into the QGIS profile |
| `resources.qrc`, `resources.py` | Qt resources (icon). Compile `resources.py` with `make compile` or `pb_tool compile`. |
| `generated_mcp_single_dict_with_help.py`, `qgis_algorithms.db`, `test.py` | Old one-tool-per-algorithm server. Nothing uses them any more. |

## Dependencies

`dependencies.REQUIREMENTS` pins `mcp>=1.8,<2`:
- 1.8 added the streamable HTTP transport.
- 2.x renamed `FastMCP`.

The packages are installed into `<profile>/python/dependencies/qmcp/py<major><minor>/`, and `add_dependencies_to_path()` puts that folder first on `sys.path`. A system-wide `mcp` 2.x therefore can't shadow the pinned version. The folder name includes the Python version because some dependencies (pydantic-core) contain compiled code.

The panel module (`qmcp_dockwidget.py`, which imports `mcp_tools`) is only imported after `ensure_dependencies()` succeeds. Do not import `mcp` or `mcp_tools` at the top of `qmcp.py` or `__init__.py`.

## Adding a tool

Put the tool in `mcp_tools.py`, or in `style_tools.py` if it's about appearance. For a new area, create a new module and import it at the end of `mcp_tools.py` the way `style_tools` is.

```python
from qgis.core import QgsMapLayer

from .mcp_tools import _find_layer, _refresh_layer, mcp_server


@mcp_server.tool()
def set_layer_scale_visibility(layer: str, min_scale: float = 0, max_scale: float = 0) -> dict:
    """Only draw a layer between two scales, e.g. min_scale=100000 (zoomed out)
    and max_scale=1000 (zoomed in). 0 means no limit.
    """
    found = _find_layer(layer)
    if min_scale < 0 or max_scale < 0:
        raise ValueError("Scales must not be negative")
    found.setScaleBasedVisibility(bool(min_scale or max_scale))
    found.setMinimumScale(min_scale)
    found.setMaximumScale(max_scale)
    _refresh_layer(found)
    return {"layer": found.name(), "layer_id": found.id(),
            "applied": {"min_scale": min_scale, "max_scale": max_scale}}
```

Conventions:

- **Name and docstring.** The function name becomes the tool name, and the docstring becomes the description the model reads. Write the docstring for the model: say what the tool does, what the units are, and give an example value when the format isn't obvious.
- **Typed parameters.** Type hints become the JSON schema. Use `Literal[...]` for fixed choices, so clients show the allowed values and invalid ones are rejected before your code runs. Give optional parameters a default of `None`, and treat `None` as "leave unchanged".
- **No `**kwargs`.** Every tool rejects arguments it doesn't declare (`MainThreadFastMCP._forbid_extra_arguments`). This catches misspelled and outdated parameter names instead of silently ignoring them.
- **Layer parameters** are called `layer` and resolved with `_find_layer()`. It accepts an ID or a unique name and raises a helpful error otherwise. Use `_vector_layer()` or `_raster_layer()` in `style_tools.py` when only one kind makes sense.
- **Colours** go through `_parse_color(value, parameter_name)`. Opacity is 0–1, checked with `_check_opacity`.
- **Validate everything first, then change the layer.** A rejected call must leave the project exactly as it was.
- **Raise `ValueError` with a message the model can act on**, naming the bad value and the valid alternatives. FastMCP turns the exception into a tool error.
- **After a visual change**, call `_refresh_layer(layer)`. It repaints the layer and updates its legend entry in the Layers panel.
- **Return small JSON**, in the form `{"layer": …, "layer_id": …, "applied": {…}}` for changes. Pass QGIS and Qt values through `_jsonable()`, which handles `QVariant` nulls, `QDate`, layers and lists.
- **Don't use `iface` at import time.** Call `_iface()` inside the tool. It is also the hook that tests replace.

## Testing

### In QGIS

1. Symlink the source folder into your profile so edits take effect without copying:
   ```bash
   ln -s "$PWD" ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/qmcp
   ```
2. Install the **Plugin Reloader** plugin. After an edit, reload QMCP, then click **Start** in the panel.
3. Check the tools the server actually exposes, without any client:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/mcp \
     -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -m json.tool
   ```
   To call a tool the same way:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/mcp \
     -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_layers","arguments":{}}}'
   ```
4. To test through the bridge as Claude Desktop does, keep stdin open. The bridge exits when stdin closes, which drops replies still in flight.
   ```bash
   (echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'; sleep 2) | python3 mcp_bridge.py
   ```
5. After changing tool names or parameters, restart the MCP client and start a new chat. Clients keep the tool list they loaded when they connected.

### Headless

You can run the tools without the QGIS window, using QGIS' Python with an off-screen Qt platform. `iface` doesn't exist there, so replace `_iface` with a stand-in that returns a real `QgsMapCanvas`. Tool calls must go through the server on a separate thread, while the main thread processes Qt events, because tools are dispatched to the main thread.

```python
import asyncio, os, sys, threading, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path += ["/usr/share/qgis/python/plugins",                      # processing
             os.path.expanduser("~/.local/share/QGIS/QGIS3/profiles/default/python/"
                                "dependencies/qmcp/py312"),          # mcp
             "/path/to/parent/of/qmcp"]

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
from qgis.gui import QgsMapCanvas
app = QgsApplication([], False); app.initQgis()
from processing.core.Processing import Processing; Processing.initialize()

from qmcp import mcp_tools, style_tools
canvas = QgsMapCanvas()
class FakeIface:
    def mapCanvas(self): return canvas
    def layerTreeView(self): return None
mcp_tools._iface = style_tools._iface = lambda: FakeIface()

def call(name, arguments):
    """Call a tool through the MCP server, the way a client would."""
    result = {}
    def run():
        try:
            result["value"] = asyncio.run(mcp_tools.mcp_server.call_tool(name, arguments))
        except Exception as e:
            result["error"] = e
    thread = threading.Thread(target=run); thread.start()
    while thread.is_alive():
        app.processEvents(); time.sleep(0.005)
    if "error" in result:
        raise result["error"]
    return result["value"]

QgsProject.instance().addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "pts", "memory"))
print(call("get_layers", {}))
print(call("set_layer_style", {"layer": "pts", "color": "#ff0000", "size": 4}))
```

Test each change against a point, a line, a polygon and a raster layer, and check the result with `render_map` and a `path`. Also test the failure cases: a missing layer, an invalid colour, a parameter for the wrong geometry type, and an unknown parameter. Check that each fails with a clear message and leaves `get_layer_style` unchanged.

The `test/` folder holds Plugin Builder's original unit tests (`make test`). They don't cover the MCP tools.

## Packaging

Any Python file the plugin needs must be listed in **both** of these, or the packaged plugin will fail to import:
- `pb_tool.cfg` (`python_files`)
- the `Makefile` (`PY_FILES`)

With [pb_tool](https://pypi.org/project/pb-tool/):

```bash
pb_tool compile   # builds resources.py
pb_tool deploy    # copies the plugin into your QGIS profile
pb_tool zip       # builds qmcp.zip for upload
```

With make: `make compile`, `make deploy`, `make zip`.

Do not ship the dependencies in the zip. `mcp` and its dependencies include compiled code that is specific to a platform and a Python version, so they are installed on first use instead.

Before a release:

1. Bump `version` in `metadata.txt` and add an entry to `changelog`.
2. Check that `qgisMinimumVersion` is right. `mcp` needs Python 3.10 or newer.
3. Build the zip, install it in a clean QGIS profile, and check that the dependency dialog, **Start**, **Set up Claude Desktop** and a few tool calls work.
