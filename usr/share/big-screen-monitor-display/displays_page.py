"""'My Displays' section of the configuration window.

A gallery with one card per display: the panels found by universal
discovery (read-only sysfs scan, the same one the service runs, done in a
worker thread), the displays the service drives and those configured but
unplugged. A card opens the display's own page: a large preview of what it
shows, its settings (anything on "same as default" follows the defaults
below the gallery), hardware details and tests. Test patterns, identify and
reconnect go to the running service through the command spool.

Nothing is ever sent to a device the user has not identified: unknown
serial devices only get a "choose model" assistant.
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
from gui import components as ui  # noqa: E402
from gui import deepcool_page  # noqa: E402
from gui.theme_gallery import render_theme  # noqa: E402

GLOBAL = "__global__"
CONFIDENCE = {"confirmed": N_("Confirmed"), "probable": N_("Probable"), "ambiguous": N_("Ambiguous — choose the model"),
              "unknown": N_("Unknown")}
STATE_TEXT = {"healthy": N_("Working"), "degraded": N_("Transient errors"), "recovering": N_("Reconnecting"),
              "disconnected": N_("Not connected"), "retrying": N_("Retrying"), "failed": N_("Not responding"),
              "starting": N_("Starting"), "stopped": N_("Stopped")}
STATE_KIND = {"healthy": "success", "degraded": "warning", "recovering": "warning", "retrying": "warning",
              "failed": "error", "disconnected": "error", "starting": "accent"}
VALIDATION = {"A": N_("A — validated on real hardware"),
              "B": N_("B — implemented, verified against reference data; real hardware pending"),
              "C": N_("C — protocol known, implementation in progress"),
              "D": N_("D — under investigation"), "E": N_("E — not supported")}
ORIENTATIONS = (("horizontal", N_("Horizontal (landscape)")), ("vertical", N_("Vertical (portrait)")),
                ("horizontal_flipped", N_("Horizontal, upside down")),
                ("vertical_flipped", N_("Vertical, upside down")))
PROFILES = (("auto", N_("Automatic (recommended)")), ("economy", N_("Economy")), ("balanced", N_("Balanced")),
            ("fluid", N_("Fluid")))
LED_LABELS = {"off": N_("Off"), "white": N_("White"), "red": N_("Red"), "green": N_("Green"), "blue": N_("Blue"),
              "cyan": N_("Cyan"), "magenta": N_("Magenta"), "yellow": N_("Yellow"), "orange": N_("Orange"),
              "purple": N_("Purple")}
TRANSPORT = {"usb": N_("USB"), "serial": N_("USB serial"), "memory": N_("Simulated")}


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


def scan(assigned):
    """Discovery (sysfs, read-only): run in the worker thread."""
    devices = discovery.scan_usb()
    return (discovery.discover(devices, assigned=assigned), discovery.unknown_serial_devices(devices),
            deepcool_page.unsupported_rows(devices))


class DisplaysPage:
    def __init__(self, window, run_helper):
        self.window = window
        self.run_helper = run_helper
        self.nav = None
        self.entries = {}
        self.unknown = []
        self.details = {}
        self._signature = None
        self._scan_result = None
        self._announce = False

        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Look for displays again"))
        ui.set_label(refresh, _("Look for displays again"))
        refresh.connect("clicked", lambda *_: self.refresh(force=True, announce=True))
        self.grid = ui.CardGrid(self.open_display, _("Displays"), max_columns=4)
        intro = ui.caption(_("Each display can have its own name, theme, orientation, brightness and performance. "
                             "Detection only reads USB identifiers: nothing is sent to a device to find out what it "
                             "is."))
        self.empty = Adw.StatusPage(icon_name="video-display-symbolic", title=_("No display found"),
                                    description=_("Connect the panel over USB, then look again. Supported models are "
                                                  "listed in the documentation (Compatibility)."), visible=False)
        look = Gtk.Button(label=_("Look Again"), halign=Gtk.Align.CENTER)
        look.add_css_class("pill")
        look.add_css_class("suggested-action")
        look.connect("clicked", lambda *_: self.refresh(force=True, announce=True))
        self.empty.set_child(look)
        self.other_group = Adw.PreferencesGroup(
            title=_("Other serial devices"),
            description=_("Not recognised automatically. If one of them is a display, choose its model; "
                          "otherwise leave it alone."), visible=False)
        self.other_rows = []
        self.deepcool_group = Adw.PreferencesGroup(
            title=_("Other DeepCool devices"),
            description=_("Identified by their USB ids, but their protocol is not implemented here. Nothing is sent "
                          "to them."), visible=False)
        self.deepcool_rows = []
        self.content = ui.page_layout(intro, self.grid, self.empty, self.other_group, self.deepcool_group,
                                      maximum=1200)
        self.page = ui.navigation_page(_("My Displays"), self.content, tag="displays", header_end=[refresh])

    def add_defaults(self, group):
        self.content.content_box.append(group)

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
        self._update_card(self.entries.get(display_id))

    def _collect(self, found, unknown):
        entries = {}
        for candidate in found:
            entries.setdefault(candidate.id, DisplayEntry(candidate.id)).candidate = candidate
        for display in (self.window.status or {}).get("displays") or []:
            entries.setdefault(display["id"], DisplayEntry(display["id"])).status = display
        for display_id in self._displays():
            entries.setdefault(display_id, DisplayEntry(display_id))
        unknown = [c for c in unknown if c.id not in entries]
        return entries, unknown

    # ---------------------------------------------------------- refresh
    def refresh(self, force=False, announce=False):
        """Scan in the worker; the gallery is rebuilt when the set of displays changes."""
        self._announce = self._announce or announce
        assigned = set(self._displays())
        self.window.worker.submit("discovery", lambda: scan(assigned),
                                  lambda result, error: self._scanned(result, error, force))
        return True

    def _scanned(self, result, error, force):
        if error is not None:
            result = ([], [], [])
        self._show_unsupported(result[2])
        entries, unknown = self._collect(*result[:2])
        signature = (tuple(sorted(entries)), tuple(c.id for c in unknown),
                     tuple(sorted((k, bool(e.candidate), bool(e.status)) for k, e in entries.items())))
        if force or signature != self._signature:
            self._signature = signature
            self.entries = entries
            self.unknown = unknown
            self._rebuild()
        else:
            for display_id, entry in entries.items():
                self.entries[display_id].status = entry.status
                self.entries[display_id].candidate = entry.candidate
        for entry in self.entries.values():
            self._update_card(entry)
            self._update_detail(entry)
        if self._announce:
            self._announce = False
            count = sum(1 for e in self.entries.values() if e.candidate)
            self.window.toast(_("{count} display(s) found.").format(count=count) if count else
                              _("No display found. Check the cable and the USB port."))

    def _rebuild(self):
        self.grid.clear()
        for display_id, entry in self.entries.items():
            icon = "power-profile-performance-symbolic" if self._family(entry) else "video-display-symbolic"
            card = ui.Card(entry.title, icon=icon)
            self.grid.add_card(display_id, card)
        self.empty.set_visible(not self.entries)
        self.grid.set_visible(bool(self.entries))
        for row in self.other_rows:
            self.other_group.remove(row)
        self.other_rows = []
        for candidate in self.unknown:
            device = candidate.device
            row = Adw.ActionRow(title=GLib.markup_escape_text(device.product or device.manufacturer or device.ids),
                                subtitle=f"{device.ids} · {candidate.port}" + (f" · {device.serial}"
                                                                               if device.serial else ""))
            row.add_prefix(Gtk.Image.new_from_icon_name("dialog-question-symbolic"))
            button = Gtk.Button(label=_("Choose Model…"), valign=Gtk.Align.CENTER)
            button.connect("clicked", lambda _b, c=candidate: self._assist(c))
            row.add_suffix(button)
            self.other_group.add(row)
            self.other_rows.append(row)
        self.other_group.set_visible(bool(self.unknown))
        for display_id in [d for d in self.details if d not in self.entries]:
            self.details.pop(display_id)

    def _show_unsupported(self, rows):
        for row in self.deepcool_rows:
            self.deepcool_group.remove(row)
        self.deepcool_rows = []
        for title, subtitle in rows:
            row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle))
            row.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
            self.deepcool_group.add(row)
            self.deepcool_rows.append(row)
        self.deepcool_group.set_visible(bool(rows))

    def _family(self, entry):
        return deepcool_page.family_of(entry, self._entry_settings(entry.id))

    # ---------------------------------------------------------- cards
    def _state(self, entry):
        """(text, kind) of a display for its card and page."""
        own = self._entry_settings(entry.id)
        state = (entry.status or {}).get("state")
        if own.get("enabled", True) is False:
            return _("Disabled"), None
        if state:
            return _(STATE_TEXT.get(state, state)), STATE_KIND.get(state)
        if entry.candidate and entry.candidate.auto_profile() is None and own.get("profile", "auto") == "auto":
            return _("Needs a model choice"), "warning"
        if entry.candidate:
            return _("Detected"), "accent"
        return _("Not connected"), "error"

    def _size(self, entry):
        device = (entry.status or {}).get("device")
        if device and device.get("width") and device.get("height"):
            return device["width"], device["height"]
        return None

    def _update_card(self, entry):
        if entry is None or entry.id not in self.grid.cards:
            return
        card = self.grid.cards[entry.id]
        own = self._entry_settings(entry.id)
        effective = settings.merged(self.window.values, entry.id)
        state, _kind = self._state(entry)
        family = self._family(entry)
        if family is not None:
            card.set_text(own.get("name") or entry.title, deepcool_page.card_subtitle(family, effective, state))
            card.set_tooltip_text(deepcool_page.card_tooltip(family, entry, effective))
            card.set_badge(state if _kind in ("error", "warning") else None)
            metrics_ = (entry.status or {}).get("metrics") or {}
            key = ("display", entry.id, family.id, repr(sorted(metrics_.get("fields", {}).items())),
                   metrics_.get("main"), metrics_.get("alarm"), (entry.status or {}).get("state"),
                   repr(sorted((k, repr(v)) for k, v in effective.items() if k.startswith("dc_") or k == "theme")))
            self.window.thumbnailer.request(key, deepcool_page.thumbnail_work(family, effective, entry),
                                            card.set_texture)
            return
        size = self._size(entry)
        parts = [state]
        if size:
            parts.append(f"{size[0]}×{size[1]}")
        theme = themes.REGISTRY.get(effective.get("theme")) or themes.REGISTRY["standard"]
        parts.append(_(theme.name.split(" — ")[0]))
        card.set_text(own.get("name") or entry.title, " · ".join(parts))
        card.set_badge(state if _kind in ("error", "warning") else None)
        render_size = size or self.window._device_size()
        if str(effective.get("orientation")).startswith("vertical") and render_size[0] > render_size[1]:
            render_size = (render_size[1], render_size[0])
        key = ("display", entry.id, render_size, effective.get("theme"), hash(repr(sorted(
            (k, repr(v)) for k, v in effective.items() if k not in ("displays", "kojiro")))))
        snapshot = dict(effective)
        self.window.thumbnailer.request(key, lambda: render_theme(snapshot.get("theme"), snapshot, render_size),
                                        card.set_texture)

    # ---------------------------------------------------------- detail page
    def open_display(self, display_id):
        entry = self.entries.get(display_id)
        if entry is None or self.nav is None:
            return
        page = self.details.get(display_id)
        if page is None:
            family = self._family(entry)
            page = deepcool_page.DeepCoolDetail(self, entry, family).page if family else self._build_detail(entry)
            self.details[display_id] = page
        self._update_detail(entry)
        if self.nav.get_visible_page() is not page:
            self.nav.push(page)

    def _combo(self, title, options, current, callback, subtitle=None):
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _value, label in options]))
        if subtitle:
            row.set_subtitle(subtitle)
        values = [value for value, _label in options]
        row.set_selected(values.index(current) if current in values else 0)
        row.connect("notify::selected", lambda r, _p: callback(values[r.get_selected()]))
        return row

    def _build_detail(self, entry):
        display_id = entry.id
        own = self._entry_settings(display_id)
        values = self.window.values
        preview = self.window.live_preview(None, _("What {name} shows").format(name=own.get("name") or entry.title),
                                           height=320)
        self.window.set_preview_display(preview, display_id)
        self.window._loading, loading = True, self.window._loading
        try:
            identity = Adw.PreferencesGroup(title=_("This display"),
                                            description=_("These values apply only to this display and take "
                                                          "precedence over the defaults."))
            name = Adw.EntryRow(title=_("Name"), text=own.get("name", ""), show_apply_button=True)
            name.connect("apply", lambda r: self._set(display_id, "name", r.get_text().strip()[:40] or None))
            identity.add(name)
            enabled = Adw.SwitchRow(title=_("Use this display"), active=own.get("enabled", True))
            enabled.connect("notify::active", lambda r, _p: self._set(display_id, "enabled",
                                                                      None if r.get_active() else False))
            identity.add(enabled)

            look = Adw.PreferencesGroup(title=_("Appearance"))
            theme_name = _(themes.REGISTRY.get(values.get("theme"), themes.REGISTRY["standard"]).name.split(" — ")[0])
            theme_options = [(GLOBAL, _("Same as default ({value})").format(value=theme_name))] + \
                [(info.id, _(info.name.split(" — ")[0])) for info in themes.available()]
            look.add(self._combo(_("Theme"), theme_options, own.get("theme", GLOBAL),
                                 lambda value: self._set(display_id, "theme", value),
                                 _("Theme options (colours, modules) are shared and set in the Theme Gallery.")))
            orientation = dict(ORIENTATIONS).get(values.get("orientation"), ORIENTATIONS[0][1])
            look.add(self._combo(_("Orientation"),
                                 [(GLOBAL, _("Same as default ({value})").format(value=_(orientation)))]
                                 + [(k, _(v)) for k, v in ORIENTATIONS],
                                 own.get("orientation", GLOBAL), lambda value: self._set(display_id, "orientation",
                                                                                         value)))
            levels = [(GLOBAL, _("Same as default ({value}%)").format(value=values.get("brightness", 70)))] + \
                [(level, f"{level}%") for level in range(100, -1, -10)]
            current = own.get("brightness", GLOBAL)
            if current != GLOBAL and current not in range(0, 101, 10):
                levels.append((current, f"{current}%"))
            brightness = self._combo(_("Brightness"), levels, current,
                                     lambda value: self._set(display_id, "brightness", value))
            look.add(brightness)
            profile_name = dict(PROFILES).get(values.get("performance_profile"), PROFILES[0][1])
            look.add(self._combo(_("Performance"),
                                 [(GLOBAL, _("Same as default ({value})").format(value=_(profile_name)))]
                                 + [(k, _(v)) for k, v in PROFILES],
                                 own.get("performance_profile", GLOBAL),
                                 lambda value: self._set(display_id, "performance_profile", value)))

            hardware = Adw.PreferencesGroup(title=_("Hardware"))
            detected = entry.candidate.best.profile.name if entry.candidate and entry.candidate.best else None
            auto_label = _("Automatic ({model})").format(model=_(detected)) if detected else _("Automatic")
            options = [("auto", auto_label)] + [(p.id, _(p.name)) for p in registry.PROFILES]
            hardware.add(self._combo(_("Model / protocol"), options, own.get("profile", "auto"),
                                     lambda value: self._model_changed(display_id, value),
                                     _("Choose manually only if detection is wrong or ambiguous.")))
            profile_id = own.get("profile", "auto")
            effective = registry.get(profile_id) if profile_id != "auto" else (
                entry.candidate.auto_profile() if entry.candidate else None)
            if effective is not None and effective.id == "turing_rev_c":
                hardware.add(self._combo(_("Panel size"), [("auto", _("Detect")), ("2.1", "2.1\""), ("2.8", "2.8\""),
                                                           ("5", "5\""), ("8.8", "8.8\"")],
                                         own.get("rev_c_size", "auto"),
                                         lambda value: self._set(display_id, "rev_c_size",
                                                                 None if value == "auto" else value)))
            if effective is not None and effective.id == "xuanfang_rev_b":
                hardware.add(self._combo(_("Backplate LEDs"), [(c, _(LED_LABELS[c])) for c in settings.LED_COLORS],
                                         own.get("led_color", "off"),
                                         lambda value: self._set(display_id, "led_color",
                                                                 None if value == "off" else value),
                                         _("Only the flagship model has LEDs.")))
            rows = {}
            for key, title in (("state", _("State")), ("resolution", _("Resolution")),
                               ("connection", _("Connection")), ("protocol", _("Protocol")),
                               ("transfer", _("Transfer")), ("details", _("Details"))):
                row = Adw.ActionRow(title=title, subtitle="—", subtitle_selectable=True)
                row.add_css_class("property")
                rows[key] = row
                hardware.add(row)
            rows["details"].set_subtitle_lines(8)
            state_pill = ui.pill("—")
            rows["state"].add_suffix(state_pill)
            sensors = Adw.ActionRow(title=_("Room sensors"), subtitle="—", visible=False)
            sensors.add_css_class("property")
            hardware.add(sensors)

            tests = Adw.PreferencesGroup(title=_("Tests"),
                                         description=_("A pattern stays on for a few seconds, then the theme returns."))
            identify = Adw.ActionRow(title=_("Identify"), subtitle=_("Shows this display's name on it"),
                                     activatable=True)
            identify.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
            identify.connect("activated", lambda *_: self.command({"action": "identify", "display": display_id}))
            tests.add(identify)
            pattern_row = Adw.ComboRow(title=_("Show a test pattern"),
                                       model=Gtk.StringList.new([_("Choose…")] + [
                                           _(patterns.LABELS[p]) for p in patterns.NAMES if p != "identify"]))
            names = [p for p in patterns.NAMES if p != "identify"]
            pattern_row.add_prefix(Gtk.Image.new_from_icon_name("view-grid-symbolic"))

            def on_pattern(row, _pspec):
                index = row.get_selected()
                if index > 0:
                    self.command({"action": "pattern", "pattern": names[index - 1], "display": display_id,
                                  "seconds": 10})
                    GLib.idle_add(lambda: row.set_selected(0) and False)
            pattern_row.connect("notify::selected", on_pattern)
            tests.add(pattern_row)
            reconnect = Adw.ActionRow(title=_("Reconnect"), subtitle=_("Closes and reopens this display only"),
                                      activatable=True)
            reconnect.add_prefix(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
            reconnect.connect("activated", lambda *_: self.command({"action": "reconnect", "display": display_id}))
            tests.add(reconnect)
        finally:
            self.window._loading = loading

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for group in (identity, look):
            side.append(group)
        lower = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        lower.append(hardware)
        lower.append(tests)
        content = ui.page_layout(ui.adaptive_split(preview, side), lower, maximum=1400)
        page = ui.navigation_page(own.get("name") or entry.title, content, tag=f"display-{display_id}")
        page.rows, page.sensors, page.state_pill = rows, sensors, state_pill
        page.brightness = brightness
        page.live_buttons = (identify, pattern_row)
        page.reconnect = reconnect
        page.preview = preview
        return page

    def _update_detail(self, entry):
        page = self.details.get(entry.id)
        if page is None:
            return
        if getattr(page, "deepcool", None) is not None:
            page.deepcool.update(entry, *self._state(entry))
            return
        status = entry.status or {}
        rows = page.rows
        text, kind = self._state(entry)
        ui.set_pill(page.state_pill, text, kind)
        device = status.get("device") or {}
        rows["state"].set_subtitle(_("Waiting for a model choice") if kind == "warning" and not status else
                                   ("—" if not status else _("for {seconds:.0f} s").format(
                                       seconds=status.get("state_since_s", 0))))
        rows["resolution"].set_subtitle(f"{device['width']} × {device['height']}" if device.get("width") else "—")
        source = status.get("source") or {}
        candidate = entry.candidate
        connection = []
        if source.get("transport"):
            connection.append(_(TRANSPORT.get(source["transport"], source["transport"])))
        if candidate:
            connection.append(_("USB {ids} at port {path}").format(ids=candidate.device.ids,
                                                                   path=candidate.device.path))
            if candidate.port:
                connection.append(_("serial port {port}").format(port=candidate.port))
        rows["connection"].set_subtitle(GLib.markup_escape_text(" · ".join(connection) or "—"))
        profile = registry.get(source.get("profile") or "") or (candidate.best.profile if candidate and candidate.best
                                                               else None)
        rows["protocol"].set_subtitle(GLib.markup_escape_text(
            f"{_(profile.name)} · {profile.protocol}\n{_(VALIDATION.get(profile.validation, profile.validation))}"
            if profile else "—"))
        caps = status.get("capabilities") or {}
        stats = status.get("stats") or {}
        transfer = []
        if caps:
            transfer.append(_("{encoding}, {mode}").format(
                encoding=caps.get("encoding"),
                mode=_("partial updates") if caps.get("partial_update") else _("whole frames")))
        if stats.get("frames_sent"):
            transfer.append(_("{fps:.1f} fps · {ms:.0f} ms per transfer · {recoveries} recoveries").format(
                fps=stats.get("fps", 0), ms=stats.get("transfer_ms", 0), recoveries=status.get("recoveries", 0)))
        rows["transfer"].set_subtitle(" · ".join(transfer) or "—")
        details = []
        if candidate:
            if candidate.device.serial:
                details.append(_("Serial number {serial}").format(serial=candidate.device.serial))
            for match in candidate.matches:
                details.append(f"{_(match.profile.name)}: {_(CONFIDENCE.get(match.confidence, match.confidence))}")
        firmware = (device.get("details") or {}).get("firmware") or (device.get("details") or {}).get("sub_revision")
        if firmware:
            details.append(_("Firmware: {version}").format(version=firmware))
        rows["details"].set_subtitle(GLib.markup_escape_text("\n".join(details) or "—"))
        sensors = status.get("sensors") or {}
        page.sensors.set_visible(bool(sensors))
        if sensors:
            text = []
            if sensors.get("room_temperature") is not None:
                text.append(_("{value:.1f} °C").format(value=sensors["room_temperature"]))
            if sensors.get("humidity") is not None:
                text.append(_("{value:.0f}% humidity").format(value=sensors["humidity"]))
            page.sensors.set_subtitle(" · ".join(text))
        live = status.get("state") in ("healthy", "degraded")
        for widget in page.live_buttons:
            widget.set_sensitive(live)
        page.reconnect.set_sensitive(bool(status))
        has_brightness = caps.get("brightness", True)
        page.brightness.set_sensitive(has_brightness)
        if not has_brightness:
            page.brightness.set_subtitle(_("This display has no adjustable brightness."))
        page.preview.set_badge(None if status else _("Not connected · preview"), demo=not status)

    # ---------------------------------------------------------- actions
    def _model_changed(self, display_id, value):
        self._set(display_id, "profile", None if value == "auto" else value)
        # Size/LED rows depend on the family: rebuild the page after the change is stored.
        page = self.details.pop(display_id, None)
        if page is not None and self.nav is not None and self.nav.get_visible_page() is page:
            GLib.idle_add(lambda: (self.nav.pop(), self.open_display(display_id)) and False)

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
        dialog.set_default_response("cancel")

        def response(_dialog, answer):
            if answer == "assign":
                self._set(candidate.id, "profile", options[combo.get_selected()].id)
                self.refresh(force=True)
                self.window.toast(_("Model chosen. Press Apply to start using the display."))
        dialog.connect("response", response)
        dialog.present(self.window)

    def command(self, command):
        def worker():
            ok, message = send_display_command(command, self.run_helper)
            GLib.idle_add(lambda: (self.window.toast(_("Sent to the display.")) if ok else
                                   self.window._error(_("The display did not receive the command"), message))
                          and False)
        threading.Thread(target=worker, daemon=True).start()
