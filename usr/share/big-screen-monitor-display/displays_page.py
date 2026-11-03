"""'My Displays' page of the configuration window.

Lists every panel found by universal discovery (read-only sysfs scan, the
same one the service runs), the displays the service is driving and the
ones configured but unplugged. Each display has its own name, model,
theme, orientation, brightness and performance profile; anything left on
"same as global" follows the global options. Test patterns, identify and
reconnect go to the running service through the command spool.
"""

import copy
import json
import threading

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from bsmd import patterns, runtime, settings, themes  # noqa: E402
from bsmd.displays import discovery, registry  # noqa: E402
from bsmd.i18n import N_, _  # noqa: E402

GLOBAL = "__global__"
CONFIDENCE = {"confirmed": N_("Confirmed"), "probable": N_("Probable"), "ambiguous": N_("Ambiguous — choose the model"),
              "unknown": N_("Unknown")}
STATE_TEXT = {"healthy": N_("Working"), "degraded": N_("Transient errors"), "recovering": N_("Reconnecting"),
              "disconnected": N_("Not connected"), "retrying": N_("Retrying"), "failed": N_("Not responding"),
              "starting": N_("Starting"), "stopped": N_("Stopped")}
STATE_ICON = {"healthy": "emblem-ok-symbolic", "degraded": "dialog-warning-symbolic",
              "failed": "dialog-error-symbolic"}
VALIDATION = {"A": N_("A — validated on real hardware"),
              "B": N_("B — implemented, verified against reference data; real hardware pending"),
              "C": N_("C — protocol known, implementation in progress"),
              "D": N_("D — under investigation"), "E": N_("E — not supported")}
ORIENTATIONS = (("horizontal", N_("Horizontal (landscape)")), ("vertical", N_("Vertical (portrait)")),
                ("horizontal_flipped", N_("Horizontal, upside down")), ("vertical_flipped", N_("Vertical, upside down")))
PROFILES = (("auto", N_("Automatic (recommended)")), ("economy", N_("Economy")), ("balanced", N_("Balanced")),
            ("fluid", N_("Fluid")))
LED_LABELS = {"off": N_("Off"), "white": N_("White"), "red": N_("Red"), "green": N_("Green"), "blue": N_("Blue"),
              "cyan": N_("Cyan"), "magenta": N_("Magenta"), "yellow": N_("Yellow"), "orange": N_("Orange"),
              "purple": N_("Purple")}


def send_display_command(command, run_helper):
    """Queue a per-display command for the running service (or a manual run)."""
    command = settings.validate_command(command)
    if command is None:
        return False, _("Invalid command.")
    status_file = runtime.find_status_file()
    if status_file is None:
        return False, _("The service is not running.")
    if status_file == runtime.SYSTEM_STATUS:
        return run_helper(["display-command"], json.dumps(command))
    try:
        runtime.spool_command(command, status_file)
        return True, ""
    except OSError as error:
        return False, str(error)


class DisplayEntry:
    """What the page knows about one display id."""

    def __init__(self, display_id):
        self.id = display_id
        self.candidate = None       # discovery.Candidate (plugged in now)
        self.status = None          # service status of this display
        self.unknown = False        # serial device no family recognises

    @property
    def title(self):
        if self.status and self.status.get("device"):
            return self.status["device"]["model"]
        if self.candidate and self.candidate.best:
            return _(self.candidate.best.profile.name)
        if self.candidate:
            device = self.candidate.device
            return device.product or device.manufacturer or _("Serial device {ids}").format(ids=device.ids)
        return self.id


class DisplaysPage:
    def __init__(self, window, run_helper):
        self.window = window
        self.run_helper = run_helper
        self.rows = {}
        self.entries = {}
        self._signature = None
        self.page = Adw.PreferencesPage()

        self.list_group = Adw.PreferencesGroup(
            title=_("Detected displays"),
            description=_("Each display can have its own theme, orientation and brightness. "
                          "Detection only reads USB identifiers: nothing is sent to a device to find out what it is."))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text=_("Detect displays again"), css_classes=["flat"])
        refresh.update_property([Gtk.AccessibleProperty.LABEL], [_("Detect displays again")])
        refresh.connect("clicked", lambda *_: self.refresh(force=True))
        self.list_group.set_header_suffix(refresh)
        self.page.add(self.list_group)
        self.empty_row = Adw.ActionRow(title=_("No display found"),
                                       subtitle=_("Connect the panel over USB. Supported models are listed in "
                                                  "the documentation (Compatibility)."))
        self.empty_row.add_prefix(Gtk.Image.new_from_icon_name("video-display-symbolic"))

        self.other_group = Adw.PreferencesGroup(
            title=_("Other serial devices"),
            description=_("Not recognised automatically. If one of them is a display, choose its model; "
                          "otherwise leave it alone."))
        self.page.add(self.other_group)
        self.other_rows = []

    # ---------------------------------------------------------- data
    def _displays(self):
        return self.window.values.setdefault("displays", {})

    def _entry_settings(self, display_id):
        return self._displays().get(display_id, {})

    def _set(self, display_id, key, value):
        if self.window._loading:
            return
        displays = copy.deepcopy(self._displays())
        entry = displays.setdefault(display_id, {})
        if value is None or value == GLOBAL:
            entry.pop(key, None)
        else:
            entry[key] = value
        if not entry:
            displays.pop(display_id, None)
        self.window.values["displays"] = displays
        self.window._refresh_dirty()

    def _collect(self):
        entries = {}
        devices = discovery.scan_usb()
        for candidate in discovery.discover(devices, assigned=set(self._displays())):
            entries.setdefault(candidate.id, DisplayEntry(candidate.id)).candidate = candidate
        for display in (self.window.status or {}).get("displays") or []:
            entries.setdefault(display["id"], DisplayEntry(display["id"])).status = display
        for display_id in self._displays():
            entries.setdefault(display_id, DisplayEntry(display_id))
        unknown = [c for c in discovery.unknown_serial_devices(devices) if c.id not in entries]
        return entries, unknown

    # ---------------------------------------------------------- building
    def refresh(self, force=False):
        """Rebuild when the set of displays changes; otherwise update in place."""
        entries, unknown = self._collect()
        signature = (tuple(sorted(entries)), tuple(c.id for c in unknown),
                     tuple(sorted((k, bool(e.candidate), bool(e.status)) for k, e in entries.items())))
        if force or signature != self._signature:
            self._signature = signature
            self.entries = entries
            self._rebuild(unknown)
        else:
            for display_id, entry in entries.items():
                self.entries[display_id].status = entry.status
                self.entries[display_id].candidate = entry.candidate
        for display_id, entry in self.entries.items():
            self._update_row(entry)
        return True

    def _rebuild(self, unknown):
        for row in list(self.rows.values()) + [self.empty_row]:
            if row.get_parent() is not None:
                self.list_group.remove(row)
        self.rows = {}
        self.window._loading, loading = True, self.window._loading
        try:
            for display_id in self.entries:
                row = self._build_row(self.entries[display_id])
                self.rows[display_id] = row
                self.list_group.add(row)
            if not self.entries:
                self.list_group.add(self.empty_row)
        finally:
            self.window._loading = loading
        for row in self.other_rows:
            self.other_group.remove(row)
        self.other_rows = []
        for candidate in unknown:
            device = candidate.device
            row = Adw.ActionRow(title=device.product or device.manufacturer or device.ids,
                                subtitle=f"{device.ids} · {candidate.port}" + (f" · {device.serial}" if device.serial else ""))
            button = Gtk.Button(label=_("Choose model…"), valign=Gtk.Align.CENTER)
            button.connect("clicked", lambda _b, c=candidate: self._assist(c))
            row.add_suffix(button)
            self.other_group.add(row)
            self.other_rows.append(row)
        self.other_group.set_visible(bool(unknown))

    def _combo(self, title, options, current, callback, subtitle=None):
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _value, label in options]))
        if subtitle:
            row.set_subtitle(subtitle)
        values = [value for value, _label in options]
        row.set_selected(values.index(current) if current in values else 0)
        row.connect("notify::selected", lambda r, _p: callback(values[r.get_selected()]))
        return row

    def _build_row(self, entry):
        display_id = entry.id
        own = self._entry_settings(display_id)
        values = self.window.values
        row = Adw.ExpanderRow(title=GLib.markup_escape_text(own.get("name") or entry.title))
        row.icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        row.add_prefix(row.icon)

        name = Adw.EntryRow(title=_("Name"), text=own.get("name", ""))
        name.set_show_apply_button(True)
        name.connect("apply", lambda r: self._set(display_id, "name", r.get_text().strip()[:40] or None))
        row.add_row(name)

        enabled = Adw.SwitchRow(title=_("Use this display"), active=own.get("enabled", True))
        enabled.connect("notify::active", lambda r, _p: self._set(display_id, "enabled",
                                                                  None if r.get_active() else False))
        row.add_row(enabled)

        detected = entry.candidate.best.profile.name if entry.candidate and entry.candidate.best else None
        auto_label = _("Automatic ({model})").format(model=_(detected)) if detected else _("Automatic")
        options = [("auto", auto_label)] + [(p.id, _(p.name)) for p in registry.PROFILES]
        row.add_row(self._combo(_("Model / protocol"), options, own.get("profile", "auto"),
                                lambda value: self._model_changed(display_id, value),
                                _("Choose manually only if detection is wrong or ambiguous.")))
        profile_id = own.get("profile", "auto")
        effective = registry.get(profile_id) if profile_id != "auto" else (
            entry.candidate.auto_profile() if entry.candidate else None)
        if effective is not None and effective.id == "turing_rev_c":
            row.add_row(self._combo(_("Panel size"), [("auto", _("Detect")), ("2.1", "2.1\""), ("2.8", "2.8\""),
                                                      ("5", "5\""), ("8.8", "8.8\"")],
                                    own.get("rev_c_size", "auto"),
                                    lambda value: self._set(display_id, "rev_c_size",
                                                            None if value == "auto" else value)))
        if effective is not None and effective.id == "xuanfang_rev_b":
            row.add_row(self._combo(_("Backplate LEDs"), [(c, _(LED_LABELS[c])) for c in settings.LED_COLORS],
                                    own.get("led_color", "off"),
                                    lambda value: self._set(display_id, "led_color", None if value == "off" else value),
                                    _("Only the flagship model has LEDs.")))

        theme_name = _(themes.REGISTRY.get(values.get("theme"), themes.REGISTRY["standard"]).name)
        theme_options = [(GLOBAL, _("Same as global ({value})").format(value=theme_name))] + \
            [(info.id, _(info.name)) for info in themes.available()]
        row.add_row(self._combo(_("Theme"), theme_options, own.get("theme", GLOBAL),
                                lambda value: self._set(display_id, "theme", value),
                                _("Theme options (colours, modules) follow the global theme tabs.")))
        orientation = dict(ORIENTATIONS).get(values.get("orientation"), ORIENTATIONS[0][1])
        row.add_row(self._combo(_("Orientation"),
                                [(GLOBAL, _("Same as global ({value})").format(value=_(orientation)))]
                                + [(k, _(v)) for k, v in ORIENTATIONS],
                                own.get("orientation", GLOBAL), lambda value: self._set(display_id, "orientation", value)))
        levels = [(GLOBAL, _("Same as global ({value}%)").format(value=values.get("brightness", 70)))] + \
            [(level, f"{level}%") for level in range(100, -1, -10)]
        current = own.get("brightness", GLOBAL)
        if current != GLOBAL and current not in range(0, 101, 10):
            levels.append((current, f"{current}%"))
        row.add_row(self._combo(_("Brightness"), levels, current,
                                lambda value: self._set(display_id, "brightness", value)))
        profile_name = dict(PROFILES).get(values.get("performance_profile"), PROFILES[0][1])
        row.add_row(self._combo(_("Performance"),
                                [(GLOBAL, _("Same as global ({value})").format(value=_(profile_name)))]
                                + [(k, _(v)) for k, v in PROFILES],
                                own.get("performance_profile", GLOBAL),
                                lambda value: self._set(display_id, "performance_profile", value)))

        row.info = Adw.ActionRow(title=_("Device"), subtitle="—")
        row.info.set_subtitle_selectable(True)
        row.info.set_subtitle_lines(6)
        row.add_row(row.info)
        row.sensors = Adw.ActionRow(title=_("Room sensors"), subtitle="—", visible=False)
        row.add_row(row.sensors)

        actions = Adw.ActionRow(title=_("Test"), subtitle=_("Shows a pattern for a few seconds, then the theme again."))
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        identify = Gtk.Button(label=_("Identify"), tooltip_text=_("Shows this display's name on it"))
        identify.connect("clicked", lambda *_: self._command({"action": "identify", "display": display_id}))
        box.append(identify)
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        popover = Gtk.Popover(child=menu)
        for pattern in patterns.NAMES:
            if pattern == "identify":
                continue
            item = Gtk.Button(label=_(patterns.LABELS[pattern]), css_classes=["flat"])
            item.connect("clicked", lambda _b, p=pattern: (popover.popdown(), self._command(
                {"action": "pattern", "pattern": p, "display": display_id, "seconds": 10})))
            menu.append(item)
        pattern_button = Gtk.MenuButton(label=_("Pattern"), popover=popover, tooltip_text=_("Test patterns"))
        box.append(pattern_button)
        reconnect = Gtk.Button(label=_("Reconnect"), tooltip_text=_("Closes and reopens this display only"))
        reconnect.connect("clicked", lambda *_: self._command({"action": "reconnect", "display": display_id}))
        box.append(reconnect)
        actions.add_suffix(box)
        row.actions = actions
        row.action_buttons = (identify, pattern_button, reconnect)
        row.add_row(actions)
        return row

    def _update_row(self, entry):
        row = self.rows.get(entry.id)
        if row is None:
            return
        own = self._entry_settings(entry.id)
        status = entry.status or {}
        state = status.get("state")
        parts = []
        if own.get("enabled", True) is False:
            parts.append(_("Disabled"))
        elif state:
            parts.append(_(STATE_TEXT.get(state, state)))
        elif entry.candidate and entry.candidate.auto_profile() is None and own.get("profile", "auto") == "auto":
            parts.append(_("Waiting for a model choice"))
        elif entry.candidate:
            parts.append(_("Detected"))
        else:
            parts.append(_("Not connected"))
        device = status.get("device")
        if device:
            parts.append(f"{device['width']}x{device['height']}")
        if entry.candidate:
            parts.append(_(CONFIDENCE.get(entry.candidate.confidence, entry.candidate.confidence)))
        row.set_subtitle(GLib.markup_escape_text(" · ".join(parts)))
        row.icon.set_from_icon_name(STATE_ICON.get(state, "video-display-symbolic"))
        info = []
        source = status.get("source") or {}
        candidate = entry.candidate
        if candidate:
            usb = candidate.device
            info.append(_("USB {ids} at port {path}").format(ids=usb.ids, path=usb.path)
                        + (f" · {_('serial')} {usb.serial}" if usb.serial else ""))
            if candidate.port:
                info.append(_("Serial port {port}").format(port=candidate.port))
            for match in candidate.matches:
                info.append(f"{_(match.profile.name)}: {_(CONFIDENCE.get(match.confidence, match.confidence))}")
        profile = registry.get(source.get("profile") or "") or (candidate.best.profile if candidate and candidate.best
                                                               else None)
        if profile:
            info.append(_("Protocol: {protocol}").format(protocol=profile.protocol))
            info.append(_("Validation: {klass}").format(klass=_(VALIDATION.get(profile.validation, profile.validation))))
        if device:
            details = device.get("details") or {}
            firmware = details.get("firmware") or details.get("sub_revision")
            if firmware:
                info.append(_("Firmware: {version}").format(version=firmware))
        caps = status.get("capabilities") or {}
        if caps:
            info.append(_("Transfer: {encoding}, {mode}").format(
                encoding=caps.get("encoding"),
                mode=_("partial updates") if caps.get("partial_update") else _("whole frames")))
        stats = status.get("stats") or {}
        if stats.get("frames_sent"):
            info.append(_("{fps:.1f} fps · {ms:.0f} ms per transfer · {recoveries} recoveries").format(
                fps=stats.get("fps", 0), ms=stats.get("transfer_ms", 0), recoveries=status.get("recoveries", 0)))
        row.info.set_subtitle("\n".join(info) or "—")
        sensors = status.get("sensors") or {}
        row.sensors.set_visible(bool(sensors))
        if sensors:
            text = []
            if sensors.get("room_temperature") is not None:
                text.append(_("{value:.1f} °C").format(value=sensors["room_temperature"]))
            if sensors.get("humidity") is not None:
                text.append(_("{value:.0f}% humidity").format(value=sensors["humidity"]))
            row.sensors.set_subtitle(" · ".join(text))
        live = state in ("healthy", "degraded")
        for button in row.action_buttons[:2]:
            button.set_sensitive(live)
        row.action_buttons[2].set_sensitive(bool(status))

    # ---------------------------------------------------------- actions
    def _model_changed(self, display_id, value):
        self._set(display_id, "profile", None if value == "auto" else value)
        # Size/LED rows depend on the family: rebuild after the change is stored.
        GLib.idle_add(lambda: self.refresh(force=True) and False)

    def _assist(self, candidate):
        """Manual identification for a serial device no family recognises."""
        dialog = Adw.AlertDialog(
            heading=_("Which display is this?"),
            body=_("{device} ({ids}) was not recognised. Choose its model only if you are sure: the service will "
                   "then talk to it with that protocol. Nothing is sent before you press Apply.").format(
                device=candidate.device.product or candidate.device.ids, ids=candidate.device.ids))
        options = [p for p in registry.PROFILES if p.transport == "serial"]
        combo = Gtk.DropDown(model=Gtk.StringList.new([_(p.name) for p in options]))
        dialog.set_extra_child(combo)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("assign", _("Use this model"))
        dialog.set_response_appearance("assign", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, answer):
            if answer == "assign":
                self._set(candidate.id, "profile", options[combo.get_selected()].id)
                self.refresh(force=True)
                self.window.toast(_("Model chosen. Press Apply to start using the display."))
        dialog.connect("response", response)
        dialog.present(self.window)

    def _command(self, command):
        def worker():
            ok, message = send_display_command(command, self.run_helper)
            GLib.idle_add(lambda: None if ok else self.window._error(_("The display did not receive the command"),
                                                                     message))
        threading.Thread(target=worker, daemon=True).start()
