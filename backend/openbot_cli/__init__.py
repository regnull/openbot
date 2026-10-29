"""OpenBot Terminal Client — a command-line frontend for an OpenBot server.

This package is a terminal (CLI) alternative to the OpenBot web UI: it talks to
the same REST + Server-Sent-Events API the browser app uses, so it never
invents a new protocol. It is intentionally separate from the server's
``openbot`` package and from any other CLI experiments in the tree.
"""

from __future__ import annotations

__version__ = "0.1.0"
