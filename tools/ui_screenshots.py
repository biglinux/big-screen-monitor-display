#!/usr/bin/env python3
"""Screenshots of every section of the configuration window (development tool).

    python3 tools/ui_screenshots.py OUT_DIR [--style dark|light] [--size 1280x860]
                                    [--sections home,themes,...] [--detail themes:planet]

Same isolation as tools/ui_benchmark.py: private D-Bus session, temporary
settings, memory GSettings, private XDG directories. The service status file
is read as it is, so a connected display appears as the user sees it.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", "usr", "share", "big-screen-monitor-display"))

CHILD = r'''
import json, os, sys, time
APP, OUT, STYLE, SIZE, SECTIONS, DETAILS = sys.argv[1:7]
sys.path.insert(0, APP)
import config_gui
from gi.repository import Adw, GLib, Gtk
from gui import preferences_page

context = GLib.MainContext.default()


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        context.iteration(False)
        time.sleep(0.005)


def shot(window, name):
    pump(0.2)
    paintable = Gtk.WidgetPaintable.new(window)
    width, height = window.get_width(), window.get_height()
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    texture = window.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(os.path.join(OUT, name + ".png"))
    print("SHOT", name, flush=True)


def run(window):
    width, height = (int(v) for v in SIZE.split("x"))
    pump(2.5)
    for key in SECTIONS.split(","):
        window.show_section(key)
        pump(3.0 if key in ("themes", "big_media_player", "brother_away", "displays") else 1.5)
        shot(window, f"{key}-{STYLE}-{width}")
    for item in filter(None, DETAILS.split(",")):
        section, _sep, target = item.partition(":")
        window.show_section(section)
        pump(1.0)
        if section == "themes":
            window.theme_gallery.open_theme(target)
        elif section == "displays":
            ids = list(window.displays_page.entries)
            if ids:
                window.displays_page.open_display(ids[0])
        elif section == "big_media_player":
            window.media_page.open_options()
        pump(3.0)
        shot(window, f"{section}-{target or 'detail'}-{STYLE}-{width}")
        window.sections[section].pop_to_tag(section)
    os._exit(0)


preferences_page.load_gui_settings = lambda: {"style": STYLE}
config_gui.load_gui_settings = preferences_page.load_gui_settings
original = config_gui.ConfigWindow.__init__


def patched(self, *args, **kwargs):
    original(self, *args, **kwargs)
    width, height = (int(v) for v in SIZE.split("x"))
    self.set_default_size(width, height)
    self.connect("map", lambda w: GLib.timeout_add(1, lambda: run(w) and False))


config_gui.ConfigWindow.__init__ = patched
config_gui.main([sys.argv[0]])
'''


def main(argv):
    out = os.path.abspath(argv[0])
    os.makedirs(out, exist_ok=True)
    style = argv[argv.index("--style") + 1] if "--style" in argv else "dark"
    size = argv[argv.index("--size") + 1] if "--size" in argv else "1280x860"
    sections = argv[argv.index("--sections") + 1] if "--sections" in argv else \
        "home,displays,themes,kojiro,big_media_player,brother_away,performance,diagnostics,preferences"
    details = argv[argv.index("--detail") + 1] if "--detail" in argv else ""
    theme = argv[argv.index("--theme") + 1] if "--theme" in argv else "standard"
    tmp = tempfile.mkdtemp(prefix="bsmd-uishots-")
    try:
        sys.path.insert(0, APP)
        from bsmd import settings
        values = settings.defaults()
        values["theme"] = theme
        settings.save(values, os.path.join(tmp, "settings.json"))
        script = os.path.join(tmp, "child.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(CHILD)
        env = dict(os.environ, BSM_CONFIG=os.path.join(tmp, "settings.json"), GSETTINGS_BACKEND="memory",
                   XDG_CONFIG_HOME=os.path.join(tmp, "config"), XDG_CACHE_HOME=os.path.join(tmp, "cache"),
                   XDG_STATE_HOME=os.path.join(tmp, "state"))
        env.setdefault("LANGUAGE", "pt")
        result = subprocess.run(["dbus-run-session", "--", sys.executable, script, APP, out, style, size, sections,
                                 details], env=env, capture_output=True, text=True, timeout=300)
        shots = [line.split()[1] for line in result.stdout.splitlines() if line.startswith("SHOT ")]
        print(json.dumps(shots))
        errors = [line for line in result.stderr.splitlines() if "Traceback" in line or "Error" in line]
        if errors:
            print(result.stderr[-3000:], file=sys.stderr)
        return 0 if shots else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
