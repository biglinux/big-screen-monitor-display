#!/bin/bash
# Big Screen Monitor Display - run the monitor manually (the service uses systemd)
exec python3 -I /usr/share/big-screen-monitor-display/main.py "$@"
