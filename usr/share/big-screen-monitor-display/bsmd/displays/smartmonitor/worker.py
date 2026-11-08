"""Capture worker: ``python3 -I worker.py < request.json``.

The capture (:mod:`.capture`) rewrites process-wide state (telemetry, the
clock, PIL drawing), so the service and the configuration window run it in a
process of its own. Request (JSON on stdin)::

    {"theme": "standard", "settings": {...}, "stats": {...}, "hour": 14,
     "rotation": 0, "out": "/path/prefix"}

Writes ``<out>.dat`` (the compiled img.dat) and ``<out>.json`` (bindings and
a short report) and prints the report.
"""

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main():
    sys.path.insert(0, BASE)
    request = json.load(sys.stdin)
    from bsmd import i18n
    i18n.set_language(request["settings"].get("language", "auto"))
    from bsmd.displays.smartmonitor import capture, fields, imgdat
    hour = request.get("hour")
    if hour is not None:
        fields.T0 = fields.T0.replace(hour=int(hour))
    theme, bindings, dropped = capture.capture(request["theme"], request["settings"], request["stats"])
    theme.rotation = int(request.get("rotation", 0))
    data = imgdat.compile_theme(theme)
    out = request["out"]
    with open(out + ".dat.tmp", "wb") as handle:
        handle.write(data)
    os.replace(out + ".dat.tmp", out + ".dat")
    report = {"bindings": bindings, "dropped": dropped, "numbers": len(theme.numbers), "bars": len(theme.bars),
              "frames": 1 + len(theme.frames), "bytes": len(data)}
    with open(out + ".json.tmp", "w", encoding="utf-8") as handle:
        json.dump(report, handle)
    os.replace(out + ".json.tmp", out + ".json")
    print(json.dumps({k: v for k, v in report.items() if k != "bindings"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
