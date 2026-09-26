#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stdio <-> HTTP bridge for the QMCP server.

MCP clients that only launch local (stdio) servers, such as Claude Desktop,
run this script; it forwards each JSON-RPC message to the QMCP server running
inside QGIS. It uses only the Python standard library so it runs on any
Python 3, including the interpreter bundled with QGIS.

Usage: python mcp_bridge.py [http://127.0.0.1:8000/mcp]
"""

import json
import sys
import threading
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8000/mcp"

_stdout_lock = threading.Lock()


def log(text):
    print("[qmcp-bridge] " + text, file=sys.stderr, flush=True)


def send(message):
    data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    with _stdout_lock:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def request_ids(message):
    """IDs of the requests in a message (notifications and responses have none)."""
    items = message if isinstance(message, list) else [message]
    return [m["id"] for m in items
            if isinstance(m, dict) and "method" in m and m.get("id") is not None]


def send_error(ids, text):
    for request_id in ids:
        send({"jsonrpc": "2.0", "id": request_id,
              "error": {"code": -32000, "message": text}})


def relay_body(body, content_type):
    if "text/event-stream" in content_type:
        for line in body.decode("utf-8").splitlines():
            if line.startswith("data:") and line[5:].strip():
                relay_message(json.loads(line[5:]))
    elif body.strip():
        relay_message(json.loads(body))


def relay_message(message):
    for item in message if isinstance(message, list) else [message]:
        send(item)


def forward(url, line):
    try:
        message = json.loads(line)
    except ValueError:
        log("ignoring invalid JSON from client")
        return
    ids = request_ids(message)

    request = urllib.request.Request(url, data=line, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    try:
        # No timeout: processing algorithms can legitimately run for a long time
        with urllib.request.urlopen(request) as response:
            relay_body(response.read(), response.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        log("HTTP {} from server: {}".format(e.code, detail))
        send_error(ids, "QGIS MCP server returned HTTP {}: {}".format(e.code, detail))
    except (urllib.error.URLError, ConnectionError) as e:
        log("cannot reach {}: {}".format(url, e))
        send_error(ids, "QGIS is not reachable at {}. Open QGIS and press Start "
                        "in the QMCP panel, then try again.".format(url))
    except Exception as e:
        log("bridge error: {!r}".format(e))
        send_error(ids, "QMCP bridge error: {}".format(e))


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    log("forwarding stdio to " + url)
    for line in sys.stdin.buffer:
        if line.strip():
            # One thread per message, so a long tool call does not block others
            threading.Thread(target=forward, args=(url, line), daemon=True).start()


if __name__ == "__main__":
    main()
