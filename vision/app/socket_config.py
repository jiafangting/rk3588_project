"""Shared socket configuration for the vision service.

This project has several independent processes that all talk to the Python
vision module:

- ``vision/app/vision_socket.py`` owns the Unix Domain Socket server.
- ``voice/vision_control.py`` sends voice commands to that server.
- ``ui`` queries the same server for live status and reload notifications.
- ``rk3588/thread_vision.c`` uses the same path from the C main process.

Keep the default path here for Python code, and keep the C/script defaults in
sync with the value below.  At deployment time, prefer setting the environment
variable ``VISION_SOCKET_PATH`` instead of editing code; every Python caller in
this repository reads that variable through ``get_vision_socket_path()``.
"""

from __future__ import annotations

import os


VISION_SOCKET_ENV = "VISION_SOCKET_PATH"
DEFAULT_VISION_SOCKET_PATH = "/tmp/vision_inspection.sock"


def get_vision_socket_path() -> str:
    """Return the Unix Domain Socket path used by all Python modules.

    The environment variable is intentionally checked at import/runtime instead
    of hard-coding the deployment path in multiple files.  Empty values are
    ignored so a mistaken ``VISION_SOCKET_PATH=`` does not make clients try to
    connect to an invalid blank path.
    """

    configured_path = os.environ.get(VISION_SOCKET_ENV, "").strip()
    if configured_path:
        return configured_path
    return DEFAULT_VISION_SOCKET_PATH
