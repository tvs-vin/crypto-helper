"""The agent: a small root service that does a fixed list of jobs for the Services window.

The web app runs as an unprivileged, sandboxed user and can't start or stop system services.
The agent can, but only the operations in `protocol.OPS`, only for Crypto Helper's own
units, and only for callers whose Unix user is root or the service user (checked with
SO_PEERCRED on its private socket). It never runs a command it was sent. Who may ask is
decided by the web app (services.manage); the agent logs who asked to the journal.
"""
