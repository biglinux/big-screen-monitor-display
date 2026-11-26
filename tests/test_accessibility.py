"""Screen readers (Orca): every icon-only button has an accessible name.

In GTK 4 a tooltip becomes the accessible *description*, not the name, so an
icon-only button without ``ui.set_label()`` is read as just "button". This scan
keeps new ones from slipping in; the real Orca walk-through is still manual
(PLANNING.md, 7.1).
"""

import glob
import os
import re

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "usr", "share", "big-screen-monitor-display"))
BUTTON = re.compile(r"([\w.]+)\s*=\s*(?:Gtk|Adw)\.(?:Button|ToggleButton|MenuButton|SplitButton)\((?=[^)\n]*icon_name)")


def unnamed_icon_buttons():
    found = []
    for path in sorted(glob.glob(os.path.join(APP, "**", "*.py"), recursive=True)):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        for index, line in enumerate(lines):
            match = BUTTON.search(line)
            if not match or re.search(r"\blabel=", line):
                continue
            name = re.escape(match.group(1))
            window = "\n".join(lines[index:index + 12])
            named = (re.search(rf"set_label\(\s*{name}\b", window)
                     or re.search(rf"{name}\.update_property\(\s*\[Gtk\.AccessibleProperty\.LABEL", window)
                     or re.search(rf"{name}\.set_child\(\s*Adw\.ButtonContent\([^)]*label=", window))
            if not named:
                found.append(f"{os.path.relpath(path, APP)}:{index + 1}: {line.strip()[:100]}")
    return found


def test_icon_buttons_have_accessible_names():
    missing = unnamed_icon_buttons()
    assert not missing, "icon-only buttons without ui.set_label():\n" + "\n".join(missing)


def test_the_scan_catches_an_unnamed_button(tmp_path, monkeypatch):
    sample = tmp_path / "sample.py"
    sample.write_text('close = Gtk.Button(icon_name="window-close-symbolic", tooltip_text=_("Close"))\n'
                      'ok = Gtk.Button(icon_name="emblem-ok-symbolic")\nui.set_label(ok, _("OK"))\n')
    monkeypatch.setattr(globals()["glob"], "glob", lambda *a, **k: [str(sample)])
    assert [entry.split(": ", 1)[1] for entry in unnamed_icon_buttons()] == [
        'close = Gtk.Button(icon_name="window-close-symbolic", tooltip_text=_("Close"))']
