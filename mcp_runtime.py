# -*- coding: utf-8 -*-
"""
Runtime support for running the MCP server inside QGIS.

The MCP server runs in a background thread, but QGIS objects (the project,
layers, the map canvas, processing) must only be touched from the main GUI
thread. Every tool registered through MainThreadFastMCP is therefore
dispatched to the main thread and its result handed back to the server.
"""

import asyncio
import concurrent.futures
import functools
import threading

from mcp.server.fastmcp import FastMCP
from qgis.PyQt.QtCore import QObject, Qt, QTimer, pyqtSignal


class _MainThreadInvoker(QObject):
    """Runs submitted callables on the thread this object lives in (the GUI thread)."""

    _submitted = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._submitted.connect(self._execute, Qt.QueuedConnection)

    def submit(self, fn):
        future = concurrent.futures.Future()
        self._submitted.emit((fn, future))
        return future

    def _execute(self, job):
        fn, future = job
        # Skip jobs whose caller has already given up (e.g. server shutting down)
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn())
        except BaseException as e:
            future.set_exception(e)


# Created at import time, which happens on the GUI thread when the plugin loads
_invoker = _MainThreadInvoker()


def run_on_main_thread(fn):
    """Wrap a sync function so that awaiting it runs it on the GUI thread."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        future = _invoker.submit(functools.partial(fn, *args, **kwargs))
        return await asyncio.wrap_future(future)

    return wrapper


class MainThreadFastMCP(FastMCP):
    """FastMCP whose tools always execute on the QGIS main thread.

    Tools also reject arguments they do not declare: FastMCP ignores them by
    default, so a misspelled or outdated parameter name would be dropped
    silently instead of reported.
    """

    def tool(self, *args, **kwargs):
        register = super().tool(*args, **kwargs)

        def decorator(fn):
            register(run_on_main_thread(fn))
            self._forbid_extra_arguments(kwargs.get("name") or fn.__name__)
            return fn

        return decorator

    def _forbid_extra_arguments(self, name):
        tool = self._tool_manager.get_tool(name)
        model = tool.fn_metadata.arg_model
        tool.fn_metadata.arg_model = type(model.__name__, (model,), {
            "__module__": model.__module__,
            "model_config": dict(model.model_config, extra="forbid"),
        })
        tool.parameters["additionalProperties"] = False


class MCPServerController(QObject):
    """Starts and stops the MCP SSE server in a background thread.

    stateChanged is emitted on the GUI thread with one of
    "starting", "running", "stopping", "stopped" or "error", plus a message.
    """

    stateChanged = pyqtSignal(str, str)
    _serverExited = pyqtSignal(bool)

    def __init__(self, mcp_server, parent=None):
        super().__init__(parent)
        self._mcp_server = mcp_server
        self._uvicorn = None
        self._thread = None

        self._startupPoll = QTimer(self)
        self._startupPoll.setInterval(100)
        self._startupPoll.timeout.connect(self._checkStarted)
        self._serverExited.connect(self._onServerExited)

    @property
    def address(self):
        """Streamable HTTP endpoint; the legacy SSE endpoint is served next to it."""
        settings = self._mcp_server.settings
        return "http://{}:{}{}".format(settings.host, settings.port, settings.streamable_http_path)

    @property
    def sseAddress(self):
        settings = self._mcp_server.settings
        return "http://{}:{}{}".format(settings.host, settings.port, settings.sse_path)

    def _buildApp(self):
        """Streamable HTTP app with the deprecated SSE routes added for older clients."""
        # The session manager can only run once, so each start needs a new one
        self._mcp_server._session_manager = None
        app = self._mcp_server.streamable_http_app()
        app.router.routes.extend(self._mcp_server.sse_app().routes)
        return app

    def setPort(self, port):
        """Takes effect on the next start."""
        self._mcp_server.settings.port = port

    def isRunning(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.isRunning():
            return
        import uvicorn

        settings = self._mcp_server.settings
        config = uvicorn.Config(
            self._buildApp(),
            host=settings.host,
            port=settings.port,
            # uvicorn's default logging config would reconfigure QGIS' loggers
            log_config=None,
            log_level="warning",
            # Open streams never finish on their own; don't wait on them forever
            timeout_graceful_shutdown=2,
        )
        self._uvicorn = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._serve, args=(self._uvicorn,), name="qmcp-server", daemon=True)
        self._thread.start()
        self.stateChanged.emit("starting", "Starting MCP server...")
        self._startupPoll.start()

    def stop(self):
        """Ask the server to exit without blocking the GUI."""
        if not self.isRunning():
            return
        self._uvicorn.should_exit = True
        self.stateChanged.emit("stopping", "Stopping MCP server...")

    def shutdown(self, timeout=5):
        """Stop the server and wait for its thread (used when the plugin unloads)."""
        self._startupPoll.stop()
        if self.isRunning():
            self._uvicorn.should_exit = True
            self._thread.join(timeout)

    def _serve(self, server):
        try:
            server.run()
        except BaseException:
            # uvicorn calls sys.exit(1) when it cannot bind the port
            pass
        try:
            self._serverExited.emit(server.started)
        except RuntimeError:
            # Controller already deleted (plugin unloaded)
            pass

    def _checkStarted(self):
        if self._uvicorn is not None and self._uvicorn.started:
            self._startupPoll.stop()
            self.stateChanged.emit("running", "MCP server running at {}".format(self.address))

    def _onServerExited(self, started):
        self._startupPoll.stop()
        self._thread = None
        self._uvicorn = None
        if started:
            self.stateChanged.emit("stopped", "MCP server stopped")
        else:
            settings = self._mcp_server.settings
            self.stateChanged.emit(
                "error",
                "Could not start MCP server on {}:{} (is the port already in use?)".format(
                    settings.host, settings.port))
