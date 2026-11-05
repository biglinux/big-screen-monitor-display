"""Big Media Player data path.

    session (user)                                   system service (DynamicUser)
    ------------------------------------------       -------------------------------
    MPRIS players --D-Bus--> agent.MediaCore  --IPC-->  hub.MediaHub --> theme
    PipeWire/Pulse --pactl--> volume.*             (unix socket, SO_PEERCRED,
    artUrl --> artwork (cache, limits, RGB)         validated JSON, raw RGB art)

Modules without GLib (model, selection, ipc, hub) are imported by the
service and the tests; mpris/volume/agent need PyGObject and only run in the
user session (the agent process and the configuration window).
"""
